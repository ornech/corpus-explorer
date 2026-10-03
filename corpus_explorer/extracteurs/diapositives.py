"""Présentations (diaporamas exportés en PDF) : un passage par diapositive.

Sur une diapositive, le texte est éparpillé en petites boîtes (frises, puces sur deux colonnes, lignes coupées
mot à mot) et la police du corps est minuscule : l'extracteur générique y voit des dizaines de faux titres et
écarte des « fragments de schéma ». Une diapositive est ici une unité de sens : tout son texte, dans l'ordre de
lecture, en un passage ; section = titre de la diapositive (bloc de plus grande police).
"""
import re

import pymupdf

from ..nettoyage import texte_propre

NOM = 'diapositives'
VERSION = '3'


def _blocs(page):
    out = []
    for b in page.get_text('dict')['blocks']:
        lignes = [''.join(s['text'] for s in l['spans']).strip() for l in b.get('lines', [])]
        lignes = [l for l in lignes if l]
        if not lignes:
            continue
        taille = max((s['size'] for l in b['lines'] for s in l['spans'] if s['text'].strip()), default=0)
        # Lignes coupées mot à mot (zones de texte étroites) : on les recolle
        out.append(dict(texte=' '.join(lignes), taille=round(taille, 1), x=b['bbox'][0], y=b['bbox'][1]))
    # Ordre de lecture : colonne par colonne (tiers de la largeur), de haut en bas dans chaque colonne ;
    # un bloc qui commence dans la marge haute (titre, bandeau) passe en tête
    largeur, haut = page.rect.width, page.rect.height * 0.18
    return sorted(out, key=lambda b: (0 if b['y'] < haut else 1, 0 if b['y'] < haut else int(b['x'] / (largeur / 3)),
                                      b['y'], b['x']))


def extraire(chemin, pages_ignorees=(), motifs_ignores=(), remplacements=None, ligatures=False, **_):
    motifs = [re.compile(m) for m in motifs_ignores]
    doc = pymupdf.open(chemin)
    passages = []
    for i, page in enumerate(doc):
        if i in pages_ignorees:
            continue
        blocs = [b for b in _blocs(page) if not any(m.search(b['texte']) for m in motifs)]
        if not blocs:
            continue
        # Titre : plus grande police parmi les blocs du haut de la diapositive qui contiennent des mots
        # (pas un grand chiffre d'infographie) ; à défaut, plus grande police de la diapositive
        hauts = [b for b in blocs if b['y'] < page.rect.height * 0.35 and len(re.findall(r'[^\W\d_]{3,}', b['texte'])) >= 2]
        titre_bloc = max(hauts or blocs, key=lambda b: (b['taille'], -b['y']))
        titre = texte_propre(titre_bloc['texte'], remplacements, ligatures)
        corps = texte_propre('\n'.join(b['texte'] for b in blocs if b is not titre_bloc), remplacements, ligatures)
        if not corps:
            passages.append(dict(page=str(i + 1), section=titre, sous_section=None, volet=None, ref_externe=None,
                                 type='titre', texte=titre))
            continue
        passages.append(dict(page=str(i + 1), section=titre, sous_section=None, volet=None, ref_externe=None,
                             type='texte', texte=f'{titre} — {corps}' if titre else corps))
    return passages
