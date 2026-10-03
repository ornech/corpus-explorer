#!/usr/bin/env python3
"""Profil d'un PDF avant ingestion : mise en page, polices, encodage, tableaux, licence.
Usage : python3 profiler.py <fichier.pdf>
Sortie : un rapport texte et des options suggérées pour corpus.json (logique : corpus_explorer/profil.py, partagée
avec la page d'ajout d'un PDF)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from corpus_explorer.profil import rapport  # noqa: E402

if __name__ == '__main__':
    print(rapport(sys.argv[1]))
