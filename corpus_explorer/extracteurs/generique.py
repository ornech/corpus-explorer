"""Extracteur générique pour PDF à texte natif, une ou deux colonnes de lecture.

Titres : repérés par la taille de police (supérieure au corps du texte).
En-têtes et pieds de page : blocs répétés d'une page à l'autre dans les marges.
Schémas : fragments courts en petite police, écartés.
"""
import re
import sys
from collections import Counter

import pymupdf

from ..nettoyage import texte_propre, est_puce

NOM = 'generique'
VERSION = '15'


def _blocs(page):
    """Blocs texte avec taille de police dominante et graisse, et dimensions de la page (H, W).

    Page à l'italienne dans une page droite (texte tourné de 90°, sens de lecture vers le bas : glossaire et
    tableaux d'un référentiel) : coordonnées remises à plat, la page est traitée comme une page paysage.
    """
    blocs = page.get_text('dict')['blocks']
    sens = Counter()
    for b in blocs:
        for l in b.get('lines', []):
            sens[tuple(round(x) for x in l['dir'])] += sum(len(s['text']) for s in l['spans'])
    tournee = bool(sens) and sens.most_common(1)[0][0] == (0, 1)
    W, H = page.rect.width, page.rect.height
    out = []
    for b in blocs:
        spans = [s for l in b.get('lines', []) for s in l['spans'] if s['text'].strip()]
        if not spans:
            continue
        brut = '\n'.join(''.join(s['text'] for s in l['spans']) for l in b['lines'])
        poids = Counter()
        for s in spans:
            poids[round(s['size'], 1)] += len(s['text'])
        taille = poids.most_common(1)[0][0]
        gras = sum(len(s['text']) for s in spans if 'Bold' in s['font'] or s['flags'] & 16) > 0.6 * sum(len(s['text']) for s in spans)
        x0, y0, x1, y1 = b['bbox']
        bbox = (y0, W - x1, y1, W - x0) if tournee else b['bbox']
        out.append(dict(bbox=bbox, brut=brut, taille=taille, gras=gras, H=W if tournee else H, W=H if tournee else W))
    return out


def _numero(brut: str):
    """Numéro de page candidat d'un bloc de marge : nombre final, nombre en tête de bloc, ou chiffres romains."""
    return (re.search(r'(?:^|\s)(\d{1,3})(?:\s*/\s*\d{1,3})?$', brut)
            or re.match(r'(\d{1,3})\s*\n', brut)
            or re.fullmatch(r'([ivxl]{1,6})(?:\s+\1)?', brut))   # pages liminaires en chiffres romains (parfois doublés)


MOTS_OUTILS = r"DE|DU|DES|LA|LE|LES|L’|L'|D’|D'|ET|EN|À|A|AU|AUX|UN|UNE|SES|SON|SA|LEUR|LEURS|POUR|PAR|SUR|DANS|AVEC"
MOT_OUTIL_FIN = re.compile(rf"(?:^|\s)(?:{MOTS_OUTILS})$")
MOT_OUTIL_DEBUT = re.compile(rf"(?:{MOTS_OUTILS})(?:\s|(?<=[’']))")


def _signature(t):
    return re.sub(r'\d+', '#', t.strip().lower())[:80]


# Pages de références (bibliographie, index) : reconnues à leur contenu, quel que soit le document ou le sujet —
# majorité de lignes « Nom, Prénom 28 ; 104 » / « Cas cité : 64 » (index) ou « AUTEUR, Prénom, 1989 : titre » (bibliographie).
# Elles n'affirment rien et forment, sur la carte, des « sujets » faits de noms propres. Option garder_references.
_REF_INDEX = re.compile(r"(?:[,:]|\s)\s*\d{1,3}(?:\s*[;,\-–]\s*\d{1,3})+\s*\.?$|[:,]\s*\d{1,3}\s*$")
_REF_BIBLIO = re.compile(r"^[A-ZÀ-Ü][A-ZÀ-Ü'’\- ]{1,30},\s*[A-ZÀ-Ü]|(?:^|\s)(?:19|20)\d\d\s*[:,.)]|https?://|doi\.org|ISBN", re.I)


def page_de_references(texte: str, part: float = 0.6, lignes_min: int = 8) -> bool:
    lignes = [l.strip() for l in texte.split('\n') if len(l.strip()) >= 6]
    if len(lignes) < lignes_min:
        return False
    index = sum(bool(_REF_INDEX.search(l)) for l in lignes) / len(lignes)
    biblio = sum(bool(_REF_BIBLIO.search(l)) for l in lignes) / len(lignes)
    return max(index, biblio) >= part


def extraire(chemin, remplacements=None, ligatures=False, pages_ignorees=(), motifs_ignores=(), titres_gras=False,
            taille_corps=None, taille_section=None, garder_references=False, **_):
    motifs = [re.compile(m) for m in motifs_ignores]
    doc = pymupdf.open(chemin)
    pages = [_blocs(p) for p in doc]
    references = set() if garder_references else {i for i, p in enumerate(doc) if page_de_references(p.get_text())}
    if references:
        print(f'[{NOM}] pages de références écartées (bibliographie, index) : '
              f'{min(references) + 1}–{max(references) + 1} ({len(references)} pages)', file=sys.stderr)
    pages_ignorees = set(pages_ignorees) | references
    marge = 0.09 * doc[0].rect.height

    # Taille du corps de texte : taille la plus fréquente, pondérée par le nombre de caractères,
    # sur les seules pages extraites (les pages écartées peuvent avoir un autre corps, ex. tableaux)
    corps = Counter()
    for i, blocs in enumerate(pages):
        if i in pages_ignorees:
            continue
        for b in blocs:
            corps[b['taille']] += len(b['brut'])
    # Option taille_corps : quand les tableaux, en plus petit, l'emportent en volume sur le texte courant
    taille_corps = taille_corps or corps.most_common(1)[0][0]

    # Blocs répétés dans les marges = en-têtes / pieds de page
    repet = Counter()
    for blocs in pages:
        for s in {_signature(b['brut']) for b in blocs if b['bbox'][1] < marge or b['bbox'][3] > b['H'] - marge}:
            repet[s] += 1
    seuil = 3  # répété sur au moins 3 pages, dans la marge
    marges_repetees = {s for s, n in repet.items() if n >= seuil}

    # Un nombre qui reste le même d'une page à l'autre dans un bandeau répété n'est pas un numéro de page
    # (ex. « … VERSION 2 » en pied de chaque page) : seuls comptent les nombres qui varient.
    nombres = {}
    for blocs in pages:
        for b in blocs:
            if b['bbox'][3] > b['H'] - marge:
                m = _numero(b['brut'].strip())
                if m:
                    nombres.setdefault(_signature(b['brut']), []).append(m.group(1))
    bandeaux_fixes = {s for s, ns in nombres.items() if len(ns) >= seuil and len(set(ns)) == 1}

    # Niveaux de titre : tailles supérieures au corps, de la plus grande à la plus petite
    tailles_titres = sorted({b['taille'] for i, blocs in enumerate(pages) if i not in pages_ignorees for b in blocs
                             if b['taille'] >= taille_corps + 0.9 and len(b['brut']) < 160
                             and len(b['brut'].strip()) > 1}, reverse=True)   # une lettrine n'est pas un niveau de titre
    numerote = re.compile(r'^([IVX]+|\d+)(\.\d+)*\.?\s+\S')

    passages, section, sous_section, lettrine, niveau_prec, titre_prec = [], None, None, '', None, None
    etiquettes = {}                       # index de page → numéro imprimé retenu
    for i, blocs in enumerate(pages):
        if i in pages_ignorees:
            continue
        page_label, lu = str(i + 1), False
        garde = []
        for b in blocs:
            x0, y0, x1, y1 = b['bbox']
            hauteur, largeur = b['H'], b['W']
            dans_marge = y0 < marge or y1 > hauteur - marge
            sig = _signature(b['brut'])
            # Onglets latéraux et texte vertical
            if x0 > 0.9 * largeur or (x1 - x0 < 12 and y1 - y0 > 20):
                continue
            # Variante d'un bandeau numéroté répété (« 41 \nTITRE DU RÉFÉRENTIEL … VERSION 2 » d'un seul bloc, alors qu'en marge il
            # est coupé en deux) : écartée, numéro de page lu en tête (y compris sur les pages tournées)
            tete = re.match(r'\s*(\d{1,3})\s*\n', b['brut'])
            if tete and sig not in marges_repetees and len(b['brut'].strip()) > 30 \
                    and any(len(m) >= 30 and (sig.startswith(m) or m.startswith(sig)) for m in marges_repetees):
                page_label, lu = tete.group(1), True
                continue
            if dans_marge:
                brut = b['brut'].strip()
                m = _numero(brut)
                # Un nombre suivi de texte n'est un numéro de page que dans un pied de page répété (« © Éditeur 2017
                # 22/37 ») : le « 7 » d'une note de bas de page (« 7 Voir un exemple en annexe ») ne l'est pas
                seul = re.fullmatch(r'(\d{1,3}|[ivxl]{1,6})(\s+\1)?', brut)
                if m and y1 > hauteur - marge and len(brut) < 90 and sig not in bandeaux_fixes \
                        and (seul or sig in marges_repetees):
                    page_label, lu = m.group(1), True
                # En-tête répété portant le numéro (« 42 - TITRE DU CHAPITRE - PARTIE 3 »,
                # « PARTIE 1 - … - 23 ») ; motifs stricts, « PARTIE 2 » n'est pas la page 2
                elif not lu and y0 < marge and sig in marges_repetees and len(brut) < 120:
                    h = re.match(r'(\d{1,3})\s*[-–|]', brut) or re.search(r'[-–|]\s*(\d{1,3})$', brut)
                    if h:
                        page_label, lu = h.group(1), True
                if sig in marges_repetees or re.fullmatch(r'\s*(\d{1,3}|[ivxl]{1,6})(\s+\1)?\s*', b['brut']):
                    continue
            if any(m.search(b['brut'].replace('\n', ' ')) for m in motifs):
                continue
            # Sommaire (points de conduite) et axes de graphiques (nombres seuls)
            if re.search(r'\.{6,}', b['brut']) or re.fullmatch(r'[\d\s,.%/-]+', b['brut']):
                continue
            # Fragments de schéma : petite police et texte court
            if b['taille'] < taille_corps * 0.8 and len(b['brut'].strip()) < 60 and not re.match(r'\s*\d', b['brut']):
                continue
            garde.append(b)

        # Ordre de lecture : colonne gauche puis droite si la page est en deux colonnes
        largeur = blocs[0]['W'] if blocs else doc[0].rect.width
        milieu = largeur / 2
        etroits_g = [b for b in garde if b['bbox'][2] < milieu + 15 and b['bbox'][2] - b['bbox'][0] < 0.55 * largeur]
        etroits_d = [b for b in garde if b['bbox'][0] > milieu - 15 and b['bbox'][2] - b['bbox'][0] < 0.55 * largeur]
        deux_col = len(etroits_g) >= 2 and len(etroits_d) >= 2

        def cle(b):
            col = 1 if deux_col and b['bbox'][0] > milieu - 15 else 0
            return (col, round(b['bbox'][1]), b['bbox'][0])
        # Les blocs pleine largeur en haut de page (titres) précèdent les colonnes
        pleins = [b for b in garde if not deux_col or b['bbox'][2] - b['bbox'][0] >= 0.55 * largeur]
        colonnes = [b for b in garde if b not in pleins]
        ordonnes = sorted(pleins, key=lambda b: b['bbox'][1]) if not deux_col else \
            sorted([b for b in pleins if b['bbox'][1] < min([c['bbox'][1] for c in colonnes] or [1e9])], key=lambda b: b['bbox'][1]) + \
            sorted(colonnes, key=cle) + \
            sorted([b for b in pleins if b['bbox'][1] >= min([c['bbox'][1] for c in colonnes] or [1e9])], key=lambda b: b['bbox'][1])

        for b in ordonnes:
            t = texte_propre(b['brut'], remplacements, ligatures)
            if not t:
                continue
            # Lettrine : grande initiale décorative isolée (« L » + « a sécurité… ») → recollée au paragraphe suivant
            if len(t) == 1 and t.isalpha() and t.isupper() and b['taille'] > taille_corps * 1.5:
                lettrine = t
                continue
            if lettrine:
                t, lettrine = (lettrine + t if re.match(r'[a-zà-ÿ]', t) else t), ''
            titre_gras = b['gras'] and len(t) < 120 and numerote.match(t) and not t.endswith('.')
            # Option titres_gras : titres en gras à la taille du corps, non numérotés (« Abstract », « Appendix A. … »).
            # Une ligne seule ; niveau d'après la numérotation (1.1. → sous-section).
            gras_corps = titres_gras and b['gras'] and '\n' not in b['brut'].strip() and len(t) < 120 \
                and not t.endswith('.') and b['taille'] >= taille_corps
            if (b['taille'] in tailles_titres and len(t) < 160) or titre_gras or gras_corps:
                niveau = tailles_titres.index(b['taille']) if b['taille'] in tailles_titres else len(tailles_titres)
                if gras_corps and b['taille'] not in tailles_titres:
                    niveau = 1 if re.match(r'\d+\.\d', t) else 0
                # Option taille_section : toutes les tailles ≥ seuil ouvrent une section (ex. chapitres et objectifs)
                if taille_section and b['taille'] >= taille_section:
                    niveau = 0
                # Titre sur deux lignes en deux blocs (« Qu’est-ce qu’une organisation » + « à haute fiabilité ? ») :
                # la suite commence par une minuscule et suit immédiatement un titre de même niveau, sur la même page
                # ou, en capitales, le bloc suit immédiatement le précédent et la coupure tombe sur un mot-outil
                # (« …CADRE DE » + « GOUVERNANCE… », « …SES SYSTEMES » + « D’INFORMATION »)
                suite_capitales = titre_prec is not None and not re.search(r'[a-zà-ÿ]', t + passages[-1]['texte']) \
                    and 0 <= b['bbox'][1] - titre_prec['bbox'][3] < 0.8 * b['taille'] \
                    and (MOT_OUTIL_FIN.search(passages[-1]['texte']) or MOT_OUTIL_DEBUT.match(t))
                if passages and passages[-1]['type'] == 'titre' and passages[-1]['page'] == page_label \
                        and niveau == niveau_prec and (re.match(r'[a-zà-ÿ]', t) or suite_capitales):
                    t = passages.pop()['texte'] + ' ' + t
                niveau_prec, titre_prec = niveau, b
                if niveau == 0:
                    section, sous_section = t, None
                else:
                    sous_section = t
                typ = 'titre'
            elif len(t) < 40 and not re.search(r'[a-zà-ÿ]', t):
                continue  # étiquette de schéma en capitales
            elif b['taille'] < taille_corps * 0.85 and re.match(r'\d{1,2}[.\s]', t):   # notes en 8 pt pour un corps de 9,9
                typ = 'note'
            elif est_puce(t):
                typ = 'liste'
            else:
                typ = 'texte'
            # Suite d'un paragraphe coupé (commence par une minuscule)
            if typ in ('texte',) and passages and re.match(r'[a-zà-ÿ(]', t) \
                    and passages[-1]['type'] in ('texte', 'liste') \
                    and not passages[-1]['texte'].endswith(('.', '!', '?', ':')):
                passages[-1]['texte'] += ' ' + t
                continue
            passages.append(dict(page=page_label, section=section, sous_section=sous_section,
                                 volet=None, ref_externe=None, type=typ, texte=t, _i=i))
        etiquettes[i] = page_label if lu else None

    # Cohérence, d'après les seuls numéros réellement lus : une page encadrée par deux numéros lus cohérents entre
    # eux (écart = écart de rang dans le PDF) prend le numéro attendu — corrige un numéro aberrant (chiffre de schéma,
    # ligne d'index) et numérote une page sans numéro imprimé (qui prenait son rang dans le PDF)
    lus = sorted(i for i, e in etiquettes.items() if e and e.isdigit())
    corrige = {}
    for b in etiquettes:
        a = max((i for i in lus if i < b), default=None)
        c = min((i for i in lus if i > b), default=None)
        if a is None or c is None or int(etiquettes[c]) - int(etiquettes[a]) != c - a:
            continue
        attendu = str(int(etiquettes[a]) + b - a)
        if etiquettes[b] != attendu and not (etiquettes[b] or '').isalpha():      # pages romaines laissées telles quelles
            corrige[b] = attendu
    for p in passages:
        i = p.pop('_i')
        if i in corrige:
            p['page'] = corrige[i]
    return passages
