"""Reconnaissance de caractères refaite pour les PDF scannés (option « ocr » d'un document de corpus.json).

La couche de texte d'un scan (OCR d'origine) est souvent abîmée : mots coupés en fragments, lettres remplacées,
lignes perdues. Avec l'option, l'ingestion extrait le texte d'une copie du PDF dont la reconnaissance est refaite
par Tesseract (ocrmypdf --force-ocr) : le PDF d'origine reste intact, les pages et leur numérotation sont
conservées. La copie est gardée dans <projet>/data/ocr/, clé = empreinte du fichier + langues : refaite seulement si
le PDF change.

Prérequis système (Ubuntu) : sudo apt install ocrmypdf tesseract-ocr-fra (autres langues : tesseract-ocr-<code>).
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

from .projet import Projet

# code de langue du document (BCP-47) → langues Tesseract ; l'anglais en renfort (citations, termes techniques)
LANGUES = {'fr': 'fra', 'en': 'eng', 'de': 'deu', 'es': 'spa', 'it': 'ita', 'pt': 'por', 'nl': 'nld'}


class OcrIndisponible(RuntimeError):
    pass


def disponible() -> bool:
    return shutil.which('ocrmypdf') is not None


def langues(langue: str | None) -> str:
    principale = LANGUES.get((langue or 'fr').split('-')[0], 'fra')
    return principale if principale == 'eng' else f'{principale}+eng'


def copie(p: Projet, empreinte: str, langue: str | None) -> Path:
    return p.donnees / 'ocr' / f'{empreinte[:16]}-{langues(langue).replace("+", "-")}.pdf'


def refaire(p: Projet, chemin: Path, empreinte: str, langue: str | None) -> Path:
    """Copie du PDF à la reconnaissance refaite (depuis le cache si elle existe déjà)."""
    cible = copie(p, empreinte, langue)
    if cible.exists():
        print(f'[ocr] reconnaissance refaite reprise du cache : {cible.name}')
        return cible
    if not disponible():
        raise OcrIndisponible('Option « ocr » : ocrmypdf est absent. Installer : sudo apt install ocrmypdf '
                              'tesseract-ocr-fra (autres langues : tesseract-ocr-<code>).')
    cible.parent.mkdir(parents=True, exist_ok=True)
    partiel = cible.with_suffix('.part.pdf')
    debut = time.time()
    print(f'[ocr] reconnaissance refaite par Tesseract ({langues(langue)}) : environ 3 s par page…', flush=True)
    r = subprocess.run(['ocrmypdf', '--force-ocr', '-l', langues(langue), '--output-type', 'pdf', '-q',
                        '--jobs', str(max(1, (os.cpu_count() or 2) - 1)), str(chemin), str(partiel)],
                       capture_output=True, text=True)
    if r.returncode:
        partiel.unlink(missing_ok=True)
        raise RuntimeError(f'ocrmypdf a échoué (code {r.returncode}) : {r.stderr.strip()[-500:]}')
    os.replace(partiel, cible)
    print(f'[ocr] terminé en {time.time() - debut:.0f} s → {cible.name}')
    return cible
