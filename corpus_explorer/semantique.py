"""Recherche par le sens dans les passages : index local (e5-base) + score lexical (synonymes validés).

Construction de l'index (script d'administration, quelques minutes sur processeur) :
    python3 -m corpus_explorer.semantique

L'index est propre à l'état de la base : il est reconstruit quand les passages actifs changent
(empreinte des identifiants et des textes).
"""
import hashlib
import json
import sys

import numpy as np

from . import projet
from .db import connexion
from .sens import REGLAGE, encoder, lexical, termes_du_projet

def _passages(cx) -> list[tuple[int, str]]:
    return [(r['id'], r['texte']) for r in
            cx.execute("SELECT id, texte FROM passage WHERE statut = 'actif' ORDER BY id")]


def _empreinte(passages: list[tuple[int, str]]) -> str:
    return hashlib.sha256(json.dumps([REGLAGE['option'], passages]).encode()).hexdigest()[:16]


def construire(cx, p: projet.Projet | None = None) -> dict:
    dossier = (p or projet.courant()).index
    ps = _passages(cx)
    e = _empreinte(ps)
    f = dossier / f'passages-{e}.npy'
    dossier.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        np.save(f, encoder(REGLAGE['option'], [t for _, t in ps]).astype(np.float32))
        (dossier / f'passages-{e}.json').write_text(json.dumps([i for i, _ in ps]), encoding='utf-8')
    (dossier / 'actuel.json').write_text(json.dumps(dict(empreinte=e, n=len(ps))), encoding='utf-8')
    return dict(empreinte=e, n=len(ps))


class Index:
    """Index chargé en mémoire ; le modèle d'embeddings est chargé à la première requête."""

    def __init__(self, cx, p: projet.Projet | None = None):
        p = p or projet.courant()
        dossier = self.dossier = p.index
        self.termes = termes_du_projet(p)
        actuel = dossier / 'actuel.json'
        if not actuel.exists():
            raise FileNotFoundError
        e = json.loads(actuel.read_text(encoding='utf-8'))['empreinte']
        if e != _empreinte(_passages(cx)):
            raise LookupError('index périmé')
        self.v = np.load(dossier / f'passages-{e}.npy')
        self.ids = json.loads((dossier / f'passages-{e}.json').read_text(encoding='utf-8'))
        self.position = {i: k for k, i in enumerate(self.ids)}
        self.empreinte = e

    def chercher(self, q: str, textes: dict[int, str], candidats: list[int] | None = None, limite: int = 10,
                 alpha: float = REGLAGE['alpha'], vecteur: np.ndarray | None = None,
                 exclus: set[int] = frozenset()) -> list[tuple[int, float, float, float]]:
        """[(passage_id, score, part sens, part lexicale)] du meilleur au moins bon.
        `textes` : texte des candidats (score lexical) ; `vecteur` : requête déjà encodée (passages semblables) ;
        présélection des 300 meilleurs au sens (et des 300 meilleurs aux mots si alpha < 0,5), puis score hybride."""
        vq = vecteur if vecteur is not None else encoder(REGLAGE['option'], [q])[0]
        lignes = [self.position[i] for i in candidats] if candidats is not None else range(len(self.ids))
        lignes = np.array([k for k in lignes if self.ids[k] not in exclus], dtype=int)
        if not len(lignes):
            return []
        sens = self.v[lignes] @ vq
        haut = list(lignes[np.argsort(-sens)[:300]])
        if alpha < 0.5:                                # dosage tourné vers les mots : ne pas dépendre du seul sens
            lex_tous = lexical([q], [textes[self.ids[k]] for k in lignes], self.termes)[0]
            haut = list(dict.fromkeys(haut + list(lignes[np.argsort(-lex_tous)[:300]])))
        ids = [self.ids[k] for k in haut]
        lex = lexical([q], [textes[i] for i in ids], self.termes)[0]
        res = [(i, float(alpha * (self.v[k] @ vq) + (1 - alpha) * l), float(self.v[k] @ vq), float(l))
               for i, k, l in zip(ids, haut, lex)]
        return sorted(res, key=lambda r: -r[1])[:limite]

    def vecteur(self, passage_id: int) -> np.ndarray:
        return self.v[self.position[passage_id]]

def main():
    p = projet.courant()
    print('Index sémantique :', construire(connexion(p.db), p))


if __name__ == '__main__':
    main()
