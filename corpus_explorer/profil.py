"""Profil d'un PDF avant ingestion : mise en page, polices, encodage, tableaux, licence, et proposition d'entrée
pour corpus.json (pré-remplissage de la page d'ajout ; tout champ reste à vérifier dans le document).

    python3 -m corpus_explorer.profil <fichier.pdf>      → rapport texte (procédure /ajouter-source)
"""
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime

import pymupdf

from . import ocr
from .nettoyage import ocr_defaillant

LICENCE = re.compile(r'[^\n]*(?:[Ll]icence|[Ll]icense|©|Copyright|Tous droits|ISBN|Version \d|reproduction)[^\n]*')
# Mots-outils fréquents : la langue dont on trouve le plus de mots dans le texte
MOTS_LANGUE = {
    'fr': set('le la les des du un une et est dans pour que qui sur par avec sont pas ce cette aux'.split()),
    'en': set('the of and to in is that for on with are be this by as from or not'.split()),
    'de': set('der die das und ist nicht mit den von zu ein eine auf für sich dem'.split()),
    'es': set('el los las del que y en es por con para una se no su al'.split()),
    'it': set('il di che e la per non una sono con del della gli le si'.split()),
}
LOGICIEL_SCAN = re.compile(r'(?i)paper capture|scandall|abbyy|finereader|tesseract|clearscan|ocr|scan|readiris|omnipage')
MOTS_VIDES_ID = set('le la les des du de un une et the of and a an for on in to pour sur dans guide rapport report'.split())


def _langue(texte: str) -> str | None:
    mots = Counter(w.lower() for w in re.findall(r'[^\W\d_]+', texte))
    scores = {l: sum(mots[m] for m in ms) for l, ms in MOTS_LANGUE.items()}
    l, n = max(scores.items(), key=lambda x: x[1])
    return l if n >= 20 else None


def _ascii(t: str) -> str:
    t = re.sub(r"['’`]", ' ', t)                               # « l’énergie » : deux mots
    return unicodedata.normalize('NFD', t).encode('ascii', 'ignore').decode()


def _annee(meta: dict, couverture: str) -> int | None:
    """Année la plus récente écrite sur les premières pages (édition) ; à défaut, date de création du fichier."""
    fin = datetime.now().year + 1
    ecrites = [int(a) for a in re.findall(r'(?<!\d)(19[5-9]\d|20\d\d)(?!\d)', couverture) if int(a) <= fin]
    if ecrites:
        return max(ecrites)
    m = re.match(r'D:(\d{4})', meta.get('creationDate') or '')
    a = int(m.group(1)) if m else None
    return a if a and 1950 <= a <= fin else None


def _titre_couverture(doc) -> str | None:
    """Texte en plus grande police de la première page qui porte du texte (titre de couverture)."""
    for page in list(doc)[:2]:
        spans = [(round(s['size'], 1), s['text'].strip()) for b in page.get_text('dict')['blocks']
                 for l in b.get('lines', []) for s in l['spans'] if s['text'].strip()]
        if not spans:
            continue
        haut = max(t for t, _ in spans)
        titre = re.sub(r'\s+', ' ', ' '.join(x for t, x in spans if t >= 0.85 * haut)).strip()
        if len(titre) >= 4:
            return titre[:300]
    return None


def identifiant(editeur: str | None, titre: str | None, annee: int | None) -> str:
    """Proposition EDITEUR-SUJET-ANNEE (majuscules, sans accent) ; à corriger par l'auteur."""
    mot = lambda t, n: [w for w in re.findall(r'[A-Za-z0-9]+', _ascii(t or ''))
                        if w.lower() not in MOTS_VIDES_ID and (len(w) >= 3 or w.isdigit())][:n]
    parts = mot(editeur, 1) + mot(titre, 2) + ([str(annee)] if annee else [])
    if not mot(editeur, 1) and not mot(titre, 2):
        parts = ['DOCUMENT'] + parts
    return '-'.join(parts).upper()[:64]


def pages_scannees(doc, echantillon: int = 12) -> float:
    """Part des pages (échantillon réparti dans le document) couvertes à 70 % ou plus par une image."""
    n = doc.page_count
    indices = sorted({round(k * (n - 1) / max(1, echantillon - 1)) for k in range(min(n, echantillon))})
    scannees = 0
    for i in indices:
        page = doc[i]
        aire = page.rect.width * page.rect.height
        if any(pymupdf.Rect(im['bbox']).get_area() >= 0.7 * aire for im in page.get_image_info()):
            scannees += 1
    return scannees / len(indices) if indices else 0.0


def profiler(chemin) -> dict:
    doc = pymupdf.open(chemin)
    larg, haut = doc[0].rect.width, doc[0].rect.height
    textes = [p.get_text() for p in doc]
    mots = sum(len(t.split()) for t in textes)
    vides = [i for i, t in enumerate(textes) if len(t.strip()) < 30]

    tailles, marges, tableaux = Counter(), Counter(), []
    for i, p in enumerate(doc):
        for b in p.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    if s['text'].strip():
                        tailles[round(s['size'], 1)] += len(s['text'])
            if 'lines' in b and b['bbox'][2] - b['bbox'][0] > 40:
                marges[round(b['bbox'][0] / 20) * 20] += 1
        try:
            # Vrais tableaux seulement : au moins 3 colonnes et 4 lignes (les cadres de mise en page sont ignorés)
            if any(t.col_count >= 3 and t.row_count >= 4 for t in p.find_tables().tables):
                tableaux.append(i)
        except Exception:
            pass

    brut = '\n'.join(textes)
    suspects = {
        'apostrophe cassée (ˇ)': brut.count('ˇ'),
        'caractère de remplacement (�)': brut.count('�'),
        'pictogrammes (zone privée)': len(re.findall(r'[-]', brut)),
        'ligature suivie d\'une espace (« défi nition »)': len(re.findall(r'[a-zà-ÿ](?:fi|fl) [a-zà-ÿ]', brut)),
        'œ remplacé par S (« cSur »)': len(re.findall(r'\b[cm]Sur|\bSuvre', brut)),
        'césure U+0002': brut.count('\u0002'),
    }
    corps = tailles.most_common(1)[0][0] if tailles else None
    titres = sorted({t for t in tailles if corps and t >= corps + 0.9}, reverse=True)
    milieu = larg / 2
    col_droite = sum(n for x, n in marges.items() if x > milieu - 20)
    col_gauche = sum(n for x, n in marges.items() if x <= milieu - 20)
    deux_colonnes = col_droite > 0.25 * (col_droite + col_gauche)
    licences = [l.strip()[:160] for l in
                LICENCE.findall(textes[0] + '\n' + textes[-1] + ('\n' + textes[1] if len(textes) > 1 else ''))][:8]
    sans_texte = mots < 50 * doc.page_count * 0.2
    meta = doc.metadata or {}
    logiciel = ' '.join(filter(None, (meta.get('creator'), meta.get('producer'))))
    part_scannee = pages_scannees(doc)
    scanne = sans_texte or part_scannee >= 0.5 or bool(LOGICIEL_SCAN.search(logiciel))
    ocr_abime, frag, suspectes = ocr_defaillant(brut)
    paysage = larg > haut

    options = {'pages_ignorees': [0]}
    if scanne and (sans_texte or ocr_abime):
        options['ocr'] = True
    if suspects["ligature suivie d'une espace (« défi nition »)"] > 5:
        options['ligatures'] = True
    rempl = {}
    if suspects['apostrophe cassée (ˇ)']:
        rempl['ˇ'] = '’'
    if suspects['œ remplacé par S (« cSur »)']:
        rempl.update({'cSur': 'cœur', 'Suvre': 'œuvre'})
    if rempl:
        options['remplacements'] = rempl

    alertes = []
    if sans_texte:
        alertes.append('Très peu de texte : PDF scanné sans reconnaissance de caractères. Option « refaire l\'OCR » '
                       'cochée : le texte sera reconnu à l\'ingestion (environ 3 s par page).')
    elif scanne and ocr_abime:
        alertes.append(f'PDF scanné dont la couche de texte est abîmée ({frag:.0%} de fragments de mots, {suspectes:.0f} ‰ de '
                       'signes collés aux lettres) : option « refaire l\'OCR » cochée (environ 3 s par page).')
    elif scanne:
        alertes.append('PDF scanné avec une couche de texte qui paraît correcte : la garder ; si la relecture montre des '
                       'mots coupés ou des lettres fausses, cocher « refaire l\'OCR ».')
    if options.get('ocr') and not ocr.disponible():
        alertes.append('ocrmypdf est absent de cette machine : installer « sudo apt install ocrmypdf tesseract-ocr-fra » '
                       'avant l\'ingestion.')
    if len(tableaux) > 0.3 * doc.page_count:
        alertes.append('Contenu principal en tableaux : un extracteur propre au projet sera sans doute nécessaire '
                       '(procédure /ajouter-source).')
    if deux_colonnes:
        alertes.append('Deux colonnes : vérifier après ingestion que l\'ordre de lecture est respecté ; si les colonnes '
                       'sont deux points de vue distincts, il faut un extracteur propre au projet.')
    if paysage:
        alertes.append('Pages en paysage : s\'il s\'agit d\'un diaporama, choisir l\'extracteur « diapositives ».')
    if not licences:
        alertes.append('Aucune mention de licence trouvée : la vérifier à la source avant de diffuser quoi que ce soit.')

    # métadonnées souvent vides ou fausses (titre « Microsoft Word - … ») : la couverture d'abord
    titre_meta = (meta.get('title') or '').strip()
    titre = _titre_couverture(doc) or (titre_meta if titre_meta and not re.match(r'(?i)microsoft|untitled|sans titre', titre_meta)
                                       else None)
    editeur = (meta.get('author') or '').strip() or None
    annee = _annee(meta, '\n'.join(textes[:2]))
    return dict(
        pages=doc.page_count, format=f'{larg:.0f} × {haut:.0f} pt' + (', paysage' if paysage else ''),
        mots=mots, pages_vides=vides, scanne=scanne, logiciel=logiciel or None, part_scannee=round(part_scannee, 2),
        fragmentation=round(frag, 3), signes_suspects=round(suspectes, 1), ocr_disponible=ocr.disponible(), corps=corps, titres=titres[:6],
        marges=marges.most_common(6), deux_colonnes=deux_colonnes, tableaux=tableaux,
        anomalies={k: v for k, v in suspects.items() if v}, licences=licences,
        metadonnees={k: v for k, v in meta.items() if v and k in ('title', 'author', 'creationDate')},
        alertes=alertes,
        proposition=dict(id=identifiant(editeur, titre, annee), titre=titre, editeur=editeur, annee=annee,
                         langue=_langue(brut[:200000]), extracteur='diapositives' if paysage else 'generique',
                         options=options))


def rapport(chemin) -> str:
    r = profiler(chemin)
    l = [f"Fichier      : {chemin}",
         f"Métadonnées  : {r['metadonnees']}",
         f"Pages        : {r['pages']} ({r['format']})",
         f"Mots         : {r['mots']}  —  pages sans texte : {r['pages_vides'] or 'aucune'}",
         f"Scan         : {'oui' if r['scanne'] else 'non'} (pages couvertes par une image : {r['part_scannee']:.0%} ; "
         f"logiciel : {r['logiciel'] or '?'}) — fragments de mots : {r['fragmentation']:.1%}, "
         f"signes collés aux lettres : {r['signes_suspects']} ‰",
         f"Police corps : {r['corps']} pt  —  tailles de titres : {r['titres']}",
         f"Marges gauches (x : nb blocs) : {r['marges']}",
         f"Deux colonnes probables : {'oui' if r['deux_colonnes'] else 'non'}",
         f"Pages avec tableaux : {r['tableaux'][:15]}{' …' if len(r['tableaux']) > 15 else ''} ({len(r['tableaux'])})",
         "Anomalies d'encodage :"] + [f"  - {k} : {v}" for k, v in r['anomalies'].items()]
    l += ['Mentions de licence / édition :'] + ([f'  - {x}' for x in r['licences']] or
                                               ['  - AUCUNE : licence à vérifier à la source, laisser licence: null'])
    l += [f"\nOptions suggérées (extracteur {r['proposition']['extracteur']}) : {r['proposition']['options']}"]
    l += [f'  ⚠ {a}' for a in r['alertes']]
    return '\n'.join(l)


if __name__ == '__main__':
    print(rapport(sys.argv[1]))
