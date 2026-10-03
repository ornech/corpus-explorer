"""Carte des passages : familles du projet, page générée."""
from corpus_explorer.vue_passages import COULEURS, famille, familles


def test_familles_du_projet():
    assert familles() == ['Guides', 'Rapports'] and len(familles()) <= len(COULEURS)
    assert famille('GUIDE-TEST-2024') == 0 and famille('REPORT-TEST-2023') == 1 and famille('INCONNU') == 1


def test_carte_du_projet_de_test(base):
    """La carte se construit sur un petit corpus (réglages adaptés à sa taille) ; passe si le modèle manque."""
    import pytest
    from corpus_explorer import semantique, vue_passages
    try:
        semantique.construire(base)
    except Exception as e:
        pytest.skip(f'modèle de sens indisponible : {e}')
    page = vue_passages.construire()
    assert 'Carte des passages' in page and 'GUIDE-TEST-2024' in page and '__' not in page.split('<script type="module">')[0]
    assert 'id="navProjets"' in page and '"projet":"test"' in page        # liens vers les autres pages du projet
    vue_passages.main()                                                  # carte écrite, servie par l'API, à jour
    from fastapi.testclient import TestClient
    from corpus_explorer.api import app
    client = TestClient(app)
    assert client.get('/projets/test/carte').text == page
    assert client.get('/projets/test').json()['carte'] == 'à jour'
