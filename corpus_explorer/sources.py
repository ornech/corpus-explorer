"""Sources d'un projet : dépôt d'un PDF dans sources/, déclaration dans corpus.json, retrait d'un dépôt non déclaré.

Le texte du document n'est jamais modifié ici : l'ingestion (tâche « ajout ») en tire les passages.
"""
import json
import os
import re
import unicodedata
from pathlib import Path

from .projet import Projet

FICHIER_VALIDE = re.compile(r'[a-z0-9][a-z0-9._-]{0,120}\.pdf')
TAILLE_MAX = 300 * 1024 * 1024                    # 300 Mo


def nom_de_fichier(original: str) -> str:
    """Nom sûr dans sources/ : minuscules sans accent, tirets, extension .pdf."""
    base = Path(original or 'document').stem
    base = unicodedata.normalize('NFD', base).encode('ascii', 'ignore').decode().lower()
    base = re.sub(r'[^a-z0-9]+', '-', base).strip('-')[:100] or 'document'
    return f'{base}.pdf'


def chemin(p: Projet, fichier: str) -> Path:
    """Fichier de sources/ désigné par son nom (jamais un chemin : le nom vient d'une adresse web)."""
    if not FICHIER_VALIDE.fullmatch(fichier):
        raise ValueError(f'Nom de fichier invalide : {fichier}')
    return p.sources / fichier


def declares(p: Projet) -> set[str]:
    return {e['fichier'] for e in p.corpus()}


def non_declarees(p: Projet) -> list[str]:
    """PDF présents dans sources/ et absents de corpus.json (déposés, à déclarer)."""
    if not p.sources.exists():
        return []
    d = declares(p)
    return sorted(f.name for f in p.sources.glob('*.pdf') if f'sources/{f.name}' not in d)


async def enregistrer(p: Projet, original: str, flux) -> str:
    """Écrit le flux (morceaux d'octets) dans sources/ ; renvoie le nom du fichier.
    FileExistsError si le nom est pris, ValueError si ce n'est pas un PDF ou s'il est trop gros."""
    fichier = nom_de_fichier(original)
    cible = chemin(p, fichier)
    if cible.exists():
        raise FileExistsError(fichier)
    p.sources.mkdir(parents=True, exist_ok=True)
    partiel = cible.with_suffix('.pdf.part')
    taille, debut = 0, b''
    try:
        with partiel.open('wb') as f:
            async for morceau in flux:
                if len(debut) < 5:
                    debut += morceau[:5 - len(debut)]
                taille += len(morceau)
                if taille > TAILLE_MAX:
                    raise ValueError(f'Fichier trop gros : {TAILLE_MAX // 2**20} Mo au plus.')
                f.write(morceau)
        if debut != b'%PDF-':
            raise ValueError("Ce fichier n'est pas un PDF.")
        os.replace(partiel, cible)
    finally:
        partiel.unlink(missing_ok=True)
    return fichier


def declarer(p: Projet, entree: dict) -> dict:
    """Ajoute l'entrée à la fin de corpus.json. KeyError si l'identifiant ou le fichier est déjà déclaré,
    FileNotFoundError si le fichier n'est pas dans sources/."""
    corpus = p.corpus()
    if any(e['id'] == entree['id'] for e in corpus):
        raise KeyError(f"L'identifiant {entree['id']} est déjà utilisé dans ce projet.")
    if any(e['fichier'] == entree['fichier'] for e in corpus):
        raise KeyError(f"Le fichier {entree['fichier']} est déjà déclaré.")
    if not (p.dossier / entree['fichier']).exists():
        raise FileNotFoundError(entree['fichier'])
    corpus.append(entree)
    _ecrire(p, corpus)
    return entree


def fiche(p: Projet, doc_id: str) -> dict:
    """Entrée de corpus.json d'un document (KeyError si inconnu)."""
    for e in p.corpus():
        if e['id'] == doc_id:
            return e
    raise KeyError(doc_id)


def modifier(p: Projet, ancien_id: str, entree: dict) -> dict:
    """Remplace la fiche d'un document, à sa place dans corpus.json. LookupError si le document est inconnu ;
    KeyError si le nouvel identifiant ou le fichier appartient à un autre document ; FileNotFoundError si le fichier
    manque. Les champs que la page ne connaît pas (ajoutés à la main) sont conservés."""
    corpus = p.corpus()
    rang = next((k for k, e in enumerate(corpus) if e['id'] == ancien_id), None)
    if rang is None:
        raise LookupError(ancien_id)
    autres = corpus[:rang] + corpus[rang + 1:]
    if any(e['id'] == entree['id'] for e in autres):
        raise KeyError(f"L'identifiant {entree['id']} est déjà utilisé dans ce projet.")
    if any(e['fichier'] == entree['fichier'] for e in autres):
        raise KeyError(f"Le fichier {entree['fichier']} est déclaré par un autre document.")
    if not (p.dossier / entree['fichier']).exists():
        raise FileNotFoundError(entree['fichier'])
    corpus[rang] = {**corpus[rang], **entree}
    _ecrire(p, corpus)
    return corpus[rang]


def _ecrire(p: Projet, corpus: list[dict]) -> None:
    temporaire = p.corpus_json.with_suffix('.json.tmp')
    temporaire.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporaire, p.corpus_json)


def retirer(p: Projet, fichier: str) -> None:
    """Supprime un PDF déposé mais pas déclaré (annulation d'un ajout). KeyError s'il est déclaré."""
    c = chemin(p, fichier)
    if f'sources/{fichier}' in declares(p):
        raise KeyError(f'{fichier} est déclaré dans corpus.json : le retirer de corpus.json d\'abord.')
    if not c.exists():
        raise FileNotFoundError(fichier)
    c.unlink()


def extracteurs(p: Projet) -> list[str]:
    """Extracteurs disponibles : ceux du moteur, puis ceux du projet."""
    moteur = Path(__file__).parent / 'extracteurs'
    noms = [f.stem for f in sorted(moteur.glob('*.py')) if not f.stem.startswith('_')]
    if p.extracteurs.exists():
        noms += [f.stem for f in sorted(p.extracteurs.glob('*.py')) if not f.stem.startswith('_') and f.stem not in noms]
    return noms


def familles(p: Projet) -> list[str]:
    """Familles connues : celles de familles.json, puis celles nommées dans corpus.json."""
    ordre = json.loads(p.familles.read_text(encoding='utf-8')).get('familles', []) if p.familles.exists() else []
    return list(dict.fromkeys(ordre + [e['famille'] for e in p.corpus() if e.get('famille')]))
