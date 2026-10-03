"""Projets : un dossier réunit la configuration d'un corpus, ses sources et ses données.

Les projets vivent dans projets/ (ou dans le dossier donné par CORPUS_PROJETS). L'API les sert tous
(/projets/<nom>/…) ; les commandes d'administration agissent sur le projet courant, choisi par CORPUS_PROJET
(nom d'un dossier de projets/ ou chemin d'un dossier ; à défaut, « exemple »).

Contenu d'un dossier de projet :
    projet.json      titre, langue principale (facultatif)
    corpus.json      liste des documents ; « fichier » est relatif au dossier du projet
    familles.json    familles de documents, dans l'ordre d'affichage (facultatif)
    synonymes.yaml   formes équivalentes d'un terme, pour la recherche par le sens (facultatif)
    extracteurs/     extracteurs propres au projet (facultatif), prioritaires sur ceux du moteur
    sources/         fichiers sources (hors git)
    data/            base, index, cartes, journaux des tâches (hors git, reconstructibles)
"""
import json
import os
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
NOM_VALIDE = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')


def racine_projets() -> Path:
    return Path(os.environ.get('CORPUS_PROJETS', RACINE / 'projets')).resolve()


class Projet:
    def __init__(self, dossier: Path | str):
        self.dossier = Path(dossier).resolve()
        self.nom = self.dossier.name
        self.corpus_json = self.dossier / 'corpus.json'
        self.familles = self.dossier / 'familles.json'
        self.synonymes = self.dossier / 'synonymes.yaml'
        self.extracteurs = self.dossier / 'extracteurs'
        self.sources = self.dossier / 'sources'
        self.donnees = self.dossier / 'data'
        self.db = self.donnees / 'corpus.db'
        self.index = self.donnees / 'index-semantique'
        self.carte = self.donnees / 'passages-3d.html'
        self.evaluations = self.donnees / 'evaluations.jsonl'      # jugements de pertinence saisis sur l'essai
        self.taches = self.donnees / 'taches'

    def __repr__(self):
        return f'Projet({self.dossier})'

    def config(self) -> dict:
        f = self.dossier / 'projet.json'
        return json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}

    def titre(self) -> str:
        return self.config().get('titre') or self.nom

    def corpus(self) -> list[dict]:
        if not self.corpus_json.exists():
            raise FileNotFoundError(f'Projet sans corpus.json : {self.dossier} (CORPUS_PROJET : nom ou chemin du projet).')
        return json.loads(self.corpus_json.read_text(encoding='utf-8'))

    def chemin_source(self, entree: dict) -> Path:
        """Fichier source d'un document du corpus, relatif au dossier du projet."""
        return self.dossier / entree['fichier']


def lister() -> list[Projet]:
    """Projets de la racine : dossiers au nom valide qui contiennent un corpus.json."""
    r = racine_projets()
    return sorted((Projet(d) for d in r.iterdir() if d.is_dir() and NOM_VALIDE.fullmatch(d.name)
                   and (d / 'corpus.json').exists()), key=lambda p: p.nom) if r.exists() else []


def ouvrir(nom: str) -> Projet:
    """Projet de la racine désigné par son nom (jamais un chemin : le nom vient d'une adresse web)."""
    if not NOM_VALIDE.fullmatch(nom) or not (racine_projets() / nom / 'corpus.json').exists():
        raise LookupError(f'Projet inconnu : {nom}')
    return Projet(racine_projets() / nom)


NOTE_FAMILLES = ("Ordre d'affichage des familles de documents = ordre des couleurs sur la carte (8 au plus ; au-delà, "
                 "les familles suivantes sont regroupées dans la dernière). Chaque document de corpus.json désigne sa "
                 "famille par son nom.")


def creer(nom: str, titre: str, langue: str = 'fr') -> Projet:
    """Nouveau projet vide dans la racine : projet.json, corpus.json vide, familles.json, sources/.
    ValueError si le nom est invalide, FileExistsError si le dossier existe déjà."""
    if not NOM_VALIDE.fullmatch(nom):
        raise ValueError(f'Nom de projet invalide : {nom!r} (minuscules, chiffres, tirets ; 64 caractères au plus).')
    dossier = racine_projets() / nom
    dossier.mkdir(parents=True, exist_ok=False)
    p = Projet(dossier)
    ecrire = lambda f, d: f.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    ecrire(dossier / 'projet.json', dict(titre=titre, langue=langue))
    ecrire(p.familles, {'_note': NOTE_FAMILLES, 'familles': []})
    p.sources.mkdir()
    ecrire(p.corpus_json, [])                                 # en dernier : le dossier devient un projet listé
    return p


def courant() -> Projet:
    """Projet des commandes d'administration (CORPUS_PROJET : nom dans la racine, ou chemin)."""
    choix = os.environ.get('CORPUS_PROJET', 'exemple')
    return Projet(choix if ('/' in choix or os.sep in choix) else racine_projets() / choix)
