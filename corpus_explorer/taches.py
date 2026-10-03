"""Tâches d'administration lancées depuis la page des projets : chaque étape est une commande du moteur, exécutée
dans un processus séparé (CORPUS_PROJET = dossier du projet), journal et état dans <projet>/data/taches/.

Une seule tâche à la fois par projet. Une tâche restée « en cours » sans processus vivant (API arrêtée pendant
son exécution) est rapportée « interrompue ».
"""
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime

from .projet import RACINE, Projet

# action → étapes (modules de corpus_explorer, lancés par python3 -m)
ACTIONS = {
    'ingestion': ['ingestion'],
    'controle': ['controle'],
    'semantique': ['semantique'],
    'carte': ['vue_passages'],
    'tout': ['ingestion', 'semantique', 'vue_passages'],
    # nouveau document : contrôle en dernier, ses erreurs de qualité n'empêchent pas l'index ni la carte
    'ajout': ['ingestion', 'semantique', 'vue_passages', 'controle'],
}
AVEC_DOCUMENTS = {'ingestion', 'controle'}          # étapes limitées aux documents désignés, s'il y en a
LIBELLES = {'ingestion': 'Ingestion', 'controle': 'Contrôle', 'semantique': 'Index de sens', 'carte': 'Carte',
            'tout': 'Ingestion, index et carte', 'ajout': 'Ajout de document'}
ID_VALIDE = re.compile(r'\d{8}-\d{6}-[a-z]+')

_verrou = threading.Lock()
_en_cours: dict[str, str] = {}          # dossier du projet → identifiant de la tâche en cours dans ce processus


class TacheEnCours(Exception):
    pass


def _meta(p: Projet, ident: str):
    return p.taches / f'{ident}.json'


def _ecrire(p: Projet, t: dict) -> None:
    _meta(p, t['id']).write_text(json.dumps(t, ensure_ascii=False), encoding='utf-8')


def _maintenant() -> str:
    return datetime.now().isoformat(timespec='seconds')


def lancer(p: Projet, action: str, documents: list[str] | None = None) -> dict:
    if action not in ACTIONS:
        raise KeyError(action)
    with _verrou:
        if str(p.dossier) in _en_cours:
            raise TacheEnCours(_en_cours[str(p.dossier)])
        ident = f"{datetime.now():%Y%m%d-%H%M%S}-{action}"
        p.taches.mkdir(parents=True, exist_ok=True)
        t = dict(id=ident, action=action, libelle=LIBELLES[action], etapes=ACTIONS[action], documents=documents or [],
                 etape=None,
                 debut=_maintenant(), fin=None, etat='en cours', code=None)
        _ecrire(p, t)
        _en_cours[str(p.dossier)] = ident
    threading.Thread(target=_executer, args=(p, t), daemon=True).start()
    return t


def _executer(p: Projet, t: dict) -> None:
    env = dict(os.environ, CORPUS_PROJET=str(p.dossier), PYTHONUNBUFFERED='1')
    try:
        with (p.taches / f"{t['id']}.log").open('w', encoding='utf-8') as journal:
            for etape in t['etapes']:
                t['etape'] = etape
                _ecrire(p, t)
                journal.write(f"── {etape} ({_maintenant()})\n")
                journal.flush()
                args = t['documents'] if etape in AVEC_DOCUMENTS else []
                code = subprocess.run([sys.executable, '-m', f'corpus_explorer.{etape}', *args], cwd=RACINE, env=env,
                                      stdout=journal, stderr=subprocess.STDOUT).returncode
                t['code'] = code
                if code:
                    break
        # contrôle : code 1 = erreurs de qualité trouvées (la commande a abouti)
        t['etat'] = 'terminée' if not t['code'] else ('à revoir' if t['etape'] == 'controle' else 'échec')
    except Exception as e:                                   # lancement impossible : consigné, jamais silencieux
        t['etat'], t['erreur'] = 'échec', str(e)
    finally:
        t['fin'] = _maintenant()
        _ecrire(p, t)
        with _verrou:
            _en_cours.pop(str(p.dossier), None)


def _lire(p: Projet, f) -> dict:
    t = json.loads(f.read_text(encoding='utf-8'))
    if t['etat'] == 'en cours' and _en_cours.get(str(p.dossier)) != t['id']:
        t['etat'] = 'interrompue'
    return t


def lister(p: Projet, limite: int = 20) -> list[dict]:
    if not p.taches.exists():
        return []
    return [_lire(p, f) for f in sorted(p.taches.glob('*.json'), reverse=True)[:limite]]


def lire(p: Projet, ident: str, lignes: int = 200) -> dict:
    """État et fin du journal d'une tâche (KeyError si inconnue)."""
    if not ID_VALIDE.fullmatch(ident) or not _meta(p, ident).exists():
        raise KeyError(ident)
    t = _lire(p, _meta(p, ident))
    j = p.taches / f'{ident}.log'
    t['journal'] = '\n'.join(j.read_text(encoding='utf-8', errors='replace').splitlines()[-lignes:]) if j.exists() else ''
    return t
