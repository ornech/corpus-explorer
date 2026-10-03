"""Contrôles du corpus, quel que soit le document ou l'extracteur.

    python3 -m corpus_explorer.controle              complétude puis qualité, tout le corpus du projet
    python3 -m corpus_explorer.controle --qualite [ID…]   qualité seule (lancée aussi à la fin de l'ingestion)

Complétude : part des mots de la source retrouvés dans les passages.
Qualité :
  erreurs (code de sortie 1) — faux passages (sans mot de 3 lettres, ou seulement « Oui » / « Non ») ;
                               caractères parasites (zone Unicode privée, contrôle, « � », « ˇ »).
  avertissements             — initiale probablement perdue (premier mot inconnu du corpus, connu avec une
                               initiale) ; numéro de page qui recule dans l'ordre de lecture ; texte répété sur
                               au moins un quart des pages (bandeau non retiré) ; plus de 25 % de fragments
                               de moins de 4 mots.
Les avertissements sont des pistes à vérifier dans le PDF, pas des défauts certains.
"""
import json
import re
import sys
from collections import Counter, defaultdict

import pymupdf

from . import ocr, projet
from .db import connexion
from .nettoyage import normaliser, ocr_defaillant, porte_du_sens, texte_propre

PARASITES = re.compile(r'[-\x00-\x08\x0b\x0c\x0e-\x1f�ˇ]')
PART_PAGES_BANDEAU = 0.25
PART_FRAGMENTS = 0.25


def mots(t):
    return Counter(w.lower() for w in re.findall(r'[^\W\d_]{4,}', t))


def controler(cx, entree, p: projet.Projet | None = None):
    """Complétude : (mots de la source, mots absents, absents les plus fréquents)."""
    p = p or projet.courant()
    chemin = p.chemin_source(entree)
    if entree.get('options', {}).get('ocr'):          # comparer au texte réellement extrait : la copie refaite
        from .ingestion import sha256
        copie = ocr.copie(p, sha256(chemin), entree.get('langue'))
        chemin = copie if copie.exists() else chemin
    if chemin.suffix == '.pdf':
        doc = pymupdf.open(chemin)
        ign = set(entree.get('options', {}).get('pages_ignorees', []))
        src = mots(' '.join(texte_propre(p.get_text(), ligatures=entree.get('options', {}).get('ligatures', False))
                            for i, p in enumerate(doc) if i not in ign))
    else:
        src = mots(chemin.read_text(encoding='utf-8', errors='replace'))
    ext = mots(' '.join(r[0] for r in cx.execute(
        "SELECT texte FROM passage WHERE document_id = ? AND statut = 'actif'", (entree['id'],))))
    manque = src - ext
    total = sum(src.values())
    return total, sum(manque.values()), manque.most_common(8)


def qualite(cx, documents: list[str] | None = None) -> dict[str, dict[str, list[str]]]:
    """{document: {'erreurs': [...], 'avertissements': [...]}} pour les documents qui ont au moins un signal."""
    lignes = cx.execute("SELECT document_id, ordre, page, type, texte FROM passage WHERE statut = 'actif' "
                        "ORDER BY document_id, ordre").fetchall()
    vocabulaire = Counter(w.lower() for r in lignes for w in re.findall(r'[^\W\d_]+', r['texte']))
    par_doc = defaultdict(list)
    for r in lignes:
        par_doc[r['document_id']].append(r)
    res = {}
    for doc, ps in par_doc.items():
        if documents and doc not in documents:
            continue
        err, avert = [], []
        ex = lambda liste, n=3: ' ; '.join(repr(x[:50]) for x in liste[:n])

        faux = [p['texte'] for p in ps if not porte_du_sens(p['texte'])]
        if faux:
            err.append(f'{len(faux)} faux passage(s) : {ex(faux)}')
        parasites = [p['texte'] for p in ps if PARASITES.search(p['texte'])]
        if parasites:
            err.append(f'{len(parasites)} passage(s) avec caractères parasites : {ex(parasites)}')

        initiales = []
        for p in ps:
            m = re.match(r'([a-zà-ÿ]{3,})', p['texte'])
            if m and vocabulaire[m.group(1)] <= 1:
                w = m.group(1)
                if any(vocabulaire[c + w] >= 2 for c in 'abcdefghijlmnopqrstuvéèà'):
                    initiales.append(f"p. {p['page']} « {w}… »")
        if initiales:
            avert.append(f'{len(initiales)} initiale(s) peut-être perdue(s) : {", ".join(initiales[:5])}')

        numeros = [(p['page'], p['texte']) for p in ps if (p['page'] or '').isdigit()]
        # un retour à la p. 1 (corps du texte après les pages liminaires) est normal
        reculs = [f"p. {a} → p. {b} ({t[:40]!r})" for (a, _), (b, t) in zip(numeros, numeros[1:])
                  if int(b) < int(a) - 1 and b != '1']
        if reculs:
            avert.append(f'{len(reculs)} numéro(s) de page qui reculent : {" ; ".join(reculs[:3])}')

        nb_pages = len({p['page'] for p in ps})
        pages_du_texte = defaultdict(set)
        for p in ps:
            if p['type'] != 'titre' and len(p['texte']) >= 15:
                pages_du_texte[normaliser(p['texte'])].add(p['page'])
        bandeaux = [t for t, pg in pages_du_texte.items() if len(pg) >= max(5, PART_PAGES_BANDEAU * nb_pages)]
        if bandeaux:
            avert.append(f'{len(bandeaux)} texte(s) répété(s) sur au moins {PART_PAGES_BANDEAU:.0%} des pages '
                         f'(bandeau non retiré ?) : {ex(bandeaux)}')

        # texte d'un scan mal reconnu : mots coupés en fragments, lettres remplacées par des signes
        suspect, frag, signes = ocr_defaillant(' '.join(p['texte'] for p in ps))
        if suspect:
            avert.append(f'texte d\'OCR défaillant ? {frag:.0%} de fragments de mots, {signes:.0f} ‰ de signes collés aux '
                         'lettres (€, ~, •…) : refaire la reconnaissance (option « ocr » du document)')

        textes = [p['texte'] for p in ps if p['type'] == 'texte']
        courts = [t for t in textes if len(t.split()) < 4]
        if textes and len(courts) / len(textes) > PART_FRAGMENTS:
            avert.append(f'{len(courts)}/{len(textes)} fragments de moins de 4 mots : {ex(courts, 4)}')

        if err or avert:
            res[doc] = dict(erreurs=err, avertissements=avert)
    return res


def afficher_qualite(res: dict, documents: list[str] | None = None) -> int:
    """Rapport lisible ; renvoie le nombre de documents en erreur."""
    if not res:
        print(f"[qualité] aucun signal{' pour ' + ', '.join(documents) if documents else ''}")
        return 0
    for doc, r in res.items():
        print(f'[qualité] {doc}')
        for e in r['erreurs']:
            print(f'  ERREUR   {e}')
        for a in r['avertissements']:
            print(f'  à vérifier  {a}')
    return sum(bool(r['erreurs']) for r in res.values())


def main(args):
    p = projet.courant()
    cx = connexion()
    corpus = p.corpus()
    seule_qualite = '--qualite' in args
    ids = [a for a in args if not a.startswith('--')] or None
    if not seule_qualite:
        for e in corpus:
            if ids and e['id'] not in ids:
                continue
            total, manque, top = controler(cx, e, p)
            print(f"{e['id']:24} {total:6} mots source, {manque/total:5.1%} absents — "
                  f"{', '.join(f'{m}({n})' for m, n in top)}")
    en_erreur = afficher_qualite(qualite(cx, ids), ids)
    sys.exit(1 if en_erreur else 0)


if __name__ == '__main__':
    main(sys.argv[1:])
