"""API multi-projet (projet de test synthétique « test ») : recherche, pages, administration."""
import time

import pytest
from fastapi.testclient import TestClient

from corpus_explorer.api import app

client = TestClient(app)
P = '/projets/test'


@pytest.fixture(autouse=True)
def _base(base):
    return base


def test_sante_et_documents():
    assert client.get(f'{P}/sante').json()['passages'] > 20
    docs = {d['id']: d for d in client.get(f'{P}/documents').json()}
    assert set(docs) == {'GUIDE-TEST-2024', 'REPORT-TEST-2023'} and docs['GUIDE-TEST-2024']['rang'] == 1


def test_projet_inconnu_et_nom_invalide():
    assert client.get('/projets/inconnu/documents').status_code == 404
    assert client.get('/projets/..%2F..%2Fetc/documents').status_code == 404
    assert client.get('/projets/Test/documents').status_code == 404


def test_recherche_sans_accent_et_citation():
    r = client.get(f'{P}/recherche', params={'q': 'continuite activite'}).json()
    assert r['total'] >= 1 and r['passages'][0]['citation'].startswith('GUIDE-TEST-2024, p. ')


def test_requete_trop_courte_et_syntaxe_fts():
    assert client.get(f'{P}/recherche', params={'q': 'a b'}).status_code == 422
    assert client.get(f'{P}/recherche', params={'q': 'main AND "courante'}).status_code == 200


def test_contexte():
    pid = client.get(f'{P}/recherche', params={'q': 'porte-parole'}).json()['passages'][0]['id']
    c = client.get(f'{P}/passages/{pid}/contexte', params={'avant': 1, 'apres': 1}).json()
    assert len(c['avant']) == 1 and len(c['apres']) == 1


def test_termes_associes_du_projet():
    t = client.get(f'{P}/termes-associes', params={'q': 'tester le PCA'}).json()
    assert t[0]['canonique'] == "plan de continuité d'activité" and 'business continuity plan' in t[0]['associes']


def test_evaluations_et_bilan():
    from corpus_explorer import projet
    projet.ouvrir('test').evaluations.unlink(missing_ok=True)
    pid = client.get(f'{P}/recherche', params={'q': 'main courante'}).json()['passages'][0]['id']
    b = dict(requete='main courante', mode='sens', passage_id=pid, rang=1)
    assert client.post(f'{P}/evaluations', json=dict(b, jugement='hors-sujet')).status_code == 201
    assert client.post(f'{P}/evaluations', json=dict(b, jugement='pertinent')).status_code == 201
    assert client.post(f'{P}/evaluations', json=dict(b, passage_id=10 ** 9, jugement='partiel')).status_code == 404
    assert client.get(f'{P}/evaluations/bilan').json() == [{'mode': 'sens', 'requetes': 1, 'jugements': 1,
                                                             'precision': 1.0, 'precision_5': 1.0}]


def test_pages_et_liens():
    accueil = client.get('/')
    assert accueil.status_code == 200 and 'Projets' in accueil.text
    essai = client.get(f'{P}/essai').text
    assert 'Projet de test' in essai and 'href="carte"' in essai and "fetch('recherche?'" in essai and '__' not in essai.split('<script')[0]
    absente = client.get(f'{P}/carte')                     # carte non construite : page d'explication, liens compris
    assert absente.status_code == 404 and 'href="/"' in absente.text


def test_cors_lecture_seule():
    r = client.get(f'{P}/documents', headers={'Origin': 'null'})
    assert r.headers.get('access-control-allow-origin') == 'null'
    assert 'access-control-allow-origin' not in client.get(f'{P}/documents', headers={'Origin': 'https://exemple.org'}).headers


def test_etat_des_projets():
    projets = {p['nom']: p for p in client.get('/projets').json()}
    t = projets['test']
    assert t['titre'] == 'Projet de test' and t['documents'] == 2 and t['ingeres'] == 2 and t['passages'] > 20
    assert t['sources_manquantes'] == 0 and t['hors_corpus'] == [] and t['carte'] == 'absente'
    assert client.get(P).json()['nom'] == 'test'


def test_creation_de_projet():
    from corpus_explorer import projet
    r = client.post('/projets', json={'nom': 'veille-energie', 'titre': 'Veille énergie', 'langue': 'fr'})
    assert r.status_code == 201 and r.json()['titre'] == 'Veille énergie' and r.json()['documents'] == 0
    p = projet.ouvrir('veille-energie')
    assert p.sources.is_dir() and p.corpus() == [] and p.config()['langue'] == 'fr'
    assert 'veille-energie' in {x['nom'] for x in client.get('/projets').json()}
    assert client.post('/projets', json={'nom': 'veille-energie', 'titre': 'Doublon'}).status_code == 409
    for nom in ('../evasion', 'Majuscules', '', 'a/b'):
        assert client.post('/projets', json={'nom': nom, 'titre': 'x'}).status_code == 422
    assert client.post('/projets', json={'nom': 'sans-titre', 'titre': ''}).status_code == 422
    assert client.post('/projets', content='{"nom": "csrf", "titre": "x"}', headers={'Content-Type': 'text/plain'}).status_code == 422
    import shutil
    shutil.rmtree(p.dossier)


def test_tache_de_fond_et_journal():
    # une écriture n'accepte que du JSON : un formulaire d'un autre site ne peut pas la déclencher
    assert client.post(f'{P}/taches', content='{"action": "controle"}',
                       headers={'Content-Type': 'text/plain'}).status_code == 422
    assert client.post(f'{P}/taches', json={'action': 'supprimer'}).status_code == 422
    t = client.post(f'{P}/taches', json={'action': 'controle'})
    assert t.status_code == 202
    ident = t.json()['id']
    for _ in range(120):
        r = client.get(f'{P}/taches/{ident}').json()
        if r['etat'] != 'en cours':
            break
        time.sleep(0.5)
    assert r['etat'] in ('terminée', 'à revoir') and 'GUIDE-TEST-2024' in r['journal']
    assert client.get(f'{P}/taches').json()[0]['id'] == ident
    assert client.get(f'{P}/taches/inconnue').status_code == 404


def test_recherche_par_le_sens_sans_mot_commun(base):
    """Construit l'index du projet de test (modèle e5-base local) ; passe si le modèle n'est pas disponible."""
    from corpus_explorer import semantique
    try:
        semantique.construire(base)
    except Exception as e:                                         # modèle absent : pas de téléchargement en test
        pytest.skip(f'modèle de sens indisponible : {e}')
    r = client.get(f'{P}/recherche-sens', params={'q': 'qui parle aux journalistes ?', 'limite': 3}).json()
    textes = ' '.join(p['texte'] for p in r['passages'])
    assert 'porte-parole' in textes or 'spokesperson' in textes
    assert client.get('/projets').json()[0]['index'] == 'à jour'
