"""Représentation du sens des passages : embeddings multilingues locaux (processeur) + score lexical.

Score hybride d'une paire de textes : α × cosinus des embeddings + (1 − α) × recouvrement des termes
normalisés. Le recouvrement ramène d'abord les formes équivalentes déclarées dans le synonymes.yaml du projet
(facultatif) à leur forme canonique.

synonymes.yaml (projet) :
    changement climatique: [réchauffement climatique, climate change]
    OMS: [Organisation mondiale de la santé, WHO]
"""
import os
import re
from pathlib import Path

import numpy as np

from . import projet
from .nettoyage import normaliser

# Modèles fastembed : cache durable (par défaut fastembed les range dans /tmp, effacé au redémarrage)
CACHE_MODELES = str(Path(os.environ.get('FASTEMBED_CACHE_PATH', Path.home() / '.cache' / 'fastembed')))

OPTIONS = {
    'A': dict(bibliotheque='fastembed', modele='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
              prefixe=''),
    'B': dict(bibliotheque='sentence-transformers', modele='intfloat/multilingual-e5-small',
              prefixe='query: '),   # e5 : préfixe « query: » pour une comparaison symétrique
    'C': dict(bibliotheque='sentence-transformers', modele='intfloat/multilingual-e5-base',
              prefixe='query: '),
}
# Représentation retenue (banc d'essai sur un corpus de guides français et anglais) : e5-base + 30 % de score lexical
REGLAGE = dict(option=os.environ.get('CORPUS_MODELE', 'C'), alpha=0.7)

_modeles = {}


def _modele(option: str):
    """Modèle d'embeddings chargé une seule fois par processus (le recharger coûte une à plusieurs secondes)."""
    if option not in _modeles:
        o = OPTIONS[option]
        if o['bibliotheque'] == 'fastembed':
            from fastembed import TextEmbedding
            m = TextEmbedding(model_name=o['modele'], cache_dir=CACHE_MODELES)
            _modeles[option] = lambda t: np.array(list(m.embed(t)))
        else:
            from sentence_transformers import SentenceTransformer
            m = SentenceTransformer(o['modele'], device='cpu')
            _modeles[option] = lambda t: m.encode(t, show_progress_bar=False)
    return _modeles[option]


def encoder(option: str, textes: list[str]) -> np.ndarray:
    o = OPTIONS[option]
    v = _modele(option)([o['prefixe'] + t for t in textes])
    return v / np.linalg.norm(v, axis=1, keepdims=True)


# ───────────── Score lexical ─────────────
MOTS_VIDES = set('dans pour avec sans sous plus leur leurs cette elle elles sont etre avoir from with that this '
                 'their have been will during each every'.split())
_normaliseurs = {}


def termes_du_projet(p: 'projet.Projet | None' = None):
    """Fonction texte → ensemble de termes, synonymes du projet ramenés à leur forme canonique (une par projet)."""
    p = p or projet.courant()
    if p.dossier not in _normaliseurs:
        _normaliseurs[p.dossier] = _normaliseur(p)
    return _normaliseurs[p.dossier]


def _normaliseur(p):
    table = {}
    if p.synonymes.exists():
        import yaml
        for canon, formes in (yaml.safe_load(p.synonymes.read_text(encoding='utf-8')) or {}).items():
            for s in list(formes or []) + [canon]:
                table[normaliser(str(s))] = normaliser(str(canon)).replace(' ', '_')
    rx = re.compile(r'\b(' + '|'.join(re.escape(m) for m in sorted(table, key=len, reverse=True)) + r')\b') if table else None

    def termes(t: str) -> set[str]:
        t = normaliser(t)
        if rx:
            t = rx.sub(lambda m: table[m.group(1)], t)
        return {w for w in re.findall(r'[a-z_]{4,}', t) if w not in MOTS_VIDES}
    return termes


def lexical(a: list[str], b: list[str], termes=None) -> np.ndarray:
    """Recouvrement de termes normalisés (coefficient de Szymkiewicz–Simpson), matrice |a| × |b|.
    `termes` : normaliseur d'un projet (termes_du_projet) ; à défaut, celui du projet courant."""
    termes = termes or termes_du_projet()
    ta, tb = [termes(x) for x in a], [termes(x) for x in b]
    return np.array([[len(x & y) / max(1, min(len(x), len(y))) for y in tb] for x in ta])


def similarite_hybride(textes_a: list[str], textes_b: list[str], va: np.ndarray, vb: np.ndarray,
                       alpha: float = REGLAGE['alpha']) -> np.ndarray:
    return alpha * (va @ vb.T) + (1 - alpha) * lexical(textes_a, textes_b)
