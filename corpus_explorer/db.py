"""Accès à la base d'un projet. Seuls l'API et les commandes d'administration l'ouvrent."""
import sqlite3
from pathlib import Path

from . import projet

SCHEMA = Path(__file__).resolve().parent / 'schema.sql'
VERSION_SCHEMA = 1


def connexion(chemin: Path | str | None = None) -> sqlite3.Connection:
    """Connexion à une base ; à défaut, celle du projet courant (commandes d'administration)."""
    chemin = chemin or projet.courant().db
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(chemin, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    cx.execute('PRAGMA foreign_keys = ON')
    return cx


def initialiser(cx: sqlite3.Connection) -> None:
    if sqlite3.sqlite_version_info < (3, 34):
        raise RuntimeError(f'SQLite {sqlite3.sqlite_version} trop ancien : 3.34 minimum (tokenizer trigram).')
    existe = cx.execute("SELECT 1 FROM sqlite_master WHERE name = 'passage'").fetchone()
    version = cx.execute('PRAGMA user_version').fetchone()[0]
    if existe and version != VERSION_SCHEMA:
        fichier = cx.execute('PRAGMA database_list').fetchone()['file']
        raise RuntimeError(f'Base au schéma v{version}, code au schéma v{VERSION_SCHEMA} : supprimer {fichier} '
                           'puis relancer python3 -m corpus_explorer.ingestion.')
    cx.executescript(SCHEMA.read_text(encoding='utf-8'))
