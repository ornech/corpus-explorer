"""État d'un projet pour la page d'administration : documents déclarés et ingérés, index de sens, carte, tâches.
Lecture seule : ne crée ni base ni dossier.
"""
import json
import sqlite3

from . import semantique, sources, taches
from .projet import Projet


def _base(p: Projet):
    if not p.db.exists():
        return None
    cx = sqlite3.connect(f'file:{p.db}?mode=ro', uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def resume(p: Projet) -> dict:
    """Ce qu'affiche la liste des projets : titre, volumes, fraîcheur de l'index et de la carte."""
    try:
        corpus = p.corpus()
        erreur = None
    except (ValueError, OSError) as e:                       # corpus.json illisible : le dire, pas planter la liste
        corpus, erreur = [], f'corpus.json illisible : {e}'
    cx = _base(p)
    try:
        ingeres = {r['id']: r for r in cx.execute(
            '''SELECT d.id, d.extracteur, d.ingere_le, count(x.id) AS passages FROM document d
               LEFT JOIN passage x ON x.document_id = d.id AND x.statut = 'actif' GROUP BY d.id''')} if cx else {}
        empreinte = semantique._empreinte(semantique._passages(cx)) if cx else None
    finally:
        if cx:
            cx.close()
    actuel = p.index / 'actuel.json'
    index_e = json.loads(actuel.read_text(encoding='utf-8'))['empreinte'] if actuel.exists() else None
    info_carte = p.carte.with_suffix('.json')
    carte_e = json.loads(info_carte.read_text(encoding='utf-8')).get('empreinte') if info_carte.exists() else None
    fraicheur = lambda e: 'absent' if e is None else ('à jour' if e == empreinte else 'périmé')
    declares = {e['id'] for e in corpus}
    documents = [dict(id=e['id'], titre=e.get('titre'), famille=e.get('famille'), extracteur=e.get('extracteur'),
                      diffusion=e.get('diffusion'), source=p.chemin_source(e).exists(),
                      passages=ingeres[e['id']]['passages'] if e['id'] in ingeres else None,
                      ingere_le=ingeres[e['id']]['ingere_le'] if e['id'] in ingeres else None) for e in corpus]
    dernieres = taches.lister(p, 1)
    return dict(
        nom=p.nom, titre=p.titre(), langue=p.config().get('langue'), erreur=erreur,
        documents=len(corpus), ingeres=len(declares & set(ingeres)),
        sources_manquantes=sum(not d['source'] for d in documents),
        hors_corpus=sorted(set(ingeres) - declares),          # en base mais retirés de corpus.json
        passages=sum(r['passages'] for r in ingeres.values()),
        index=fraicheur(index_e) if empreinte or index_e else 'absent',
        carte='absente' if not p.carte.exists() else
              {'absent': 'à reconstruire', 'à jour': 'à jour', 'périmé': 'périmée'}[fraicheur(carte_e)],
        evaluations=sum(1 for l in p.evaluations.read_text(encoding='utf-8').splitlines() if l.strip())
                    if p.evaluations.exists() else 0,
        tache=dernieres[0] if dernieres else None,
        a_declarer=sources.non_declarees(p) if not erreur else [],     # PDF déposés dans sources/, pas dans corpus.json
        familles=sources.familles(p) if not erreur else [],
        extracteurs=sources.extracteurs(p),
        detail=documents)
