"""Ajout d'un PDF depuis la page des projets : dépôt, profil, déclaration, ingestion, refus."""
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from corpus_explorer import projet
from corpus_explorer.api import app
from corpus_explorer.profil import identifiant
from corpus_explorer.sources import nom_de_fichier

client = TestClient(app)
PDF = {'Content-Type': 'application/pdf'}


@pytest.fixture
def vide():
    """Projet vide créé pour le test, supprimé ensuite."""
    assert client.post('/projets', json={'nom': 'ajouts', 'titre': 'Ajouts', 'langue': 'fr'}).status_code == 201
    p = projet.ouvrir('ajouts')
    yield p
    shutil.rmtree(p.dossier)


def _guide():
    return (projet.ouvrir('test').sources / 'guide.pdf').read_bytes()


def test_noms_proposes():
    assert nom_de_fichier('Rapport Énergie 2025 (v2).PDF') == 'rapport-energie-2025-v2.pdf'
    assert nom_de_fichier('../../etc/passwd') == 'passwd.pdf'
    assert identifiant('Commission de régulation', 'Le rapport annuel sur l’énergie', 2025) == 'COMMISSION-ANNUEL-ENERGIE-2025'


def test_depot_declaration_et_ingestion(vide):
    r = client.post('/projets/ajouts/sources', params={'fichier': 'Guide de test.pdf'}, content=_guide(), headers=PDF)
    assert r.status_code == 201
    rep = r.json()
    assert rep['fichier'] == 'sources/guide-de-test.pdf' and rep['profil']['pages'] == 5
    assert rep['profil']['proposition']['langue'] == 'fr' and rep['profil']['proposition']['extracteur'] == 'generique'
    assert client.get('/projets/ajouts').json()['a_declarer'] == ['guide-de-test.pdf']
    assert client.get('/projets/ajouts/sources/guide-de-test.pdf/profil').status_code == 200

    doc = dict(id='ESSAI-GUIDE-2024', titre='Guide de test', editeur='Essai', annee=2024, langue='fr',
               fichier=rep['fichier'], licence='test', diffusion='public', famille='Guides', extracteur='generique',
               options=rep['profil']['proposition']['options'])
    assert client.post('/projets/ajouts/documents', json=dict(doc, diffusion=None)).status_code == 422
    assert client.post('/projets/ajouts/documents', json=dict(doc, licence='')).status_code == 422
    assert client.post('/projets/ajouts/documents', json=dict(doc, editeur=None)).status_code == 422
    assert client.post('/projets/ajouts/documents', json=dict(doc, extracteur='inexistant')).status_code == 422
    assert client.post('/projets/ajouts/documents', json=dict(doc, fichier='sources/absent.pdf')).status_code == 422
    assert client.post('/projets/ajouts/documents', json=doc).status_code == 201
    assert client.post('/projets/ajouts/documents', json=doc).status_code == 409                  # identifiant pris
    assert client.post('/projets/ajouts/documents', json=dict(doc, id='AUTRE-2024')).status_code == 409  # fichier déjà déclaré
    assert vide.corpus()[0]['id'] == 'ESSAI-GUIDE-2024'
    e = client.get('/projets/ajouts').json()
    assert e['a_declarer'] == [] and e['documents'] == 1 and e['familles'] == ['Guides']
    assert client.delete('/projets/ajouts/sources/guide-de-test.pdf').status_code == 409          # déclaré : gardé

    assert client.post('/projets/ajouts/taches', json={'action': 'ajout', 'documents': ['INCONNU']}).status_code == 422
    t = client.post('/projets/ajouts/taches', json={'action': 'ingestion', 'documents': ['ESSAI-GUIDE-2024']})
    assert t.status_code == 202
    for _ in range(120):
        r = client.get(f"/projets/ajouts/taches/{t.json()['id']}").json()
        if r['etat'] != 'en cours':
            break
        time.sleep(0.5)
    assert r['etat'] == 'terminée' and 'ESSAI-GUIDE-2024' in r['journal']
    n = client.get('/projets/ajouts').json()['passages']
    assert n > 10

    # correction de la fiche : champs ajoutés à la main conservés, identifiant changé → ancien retiré de la base
    vide.corpus_json.write_text(vide.corpus_json.read_text().replace('"options"', '"note": "à la main",\n    "options"', 1))
    f = client.get('/projets/ajouts/documents/ESSAI-GUIDE-2024/fiche').json()
    assert f['titre'] == 'Guide de test' and client.get('/projets/ajouts/documents/INCONNU/fiche').status_code == 404
    m = client.put('/projets/ajouts/documents/ESSAI-GUIDE-2024', json=dict(doc, titre='Guide corrigé'))
    assert m.status_code == 200 and m.json()['identifiant_change'] is False
    assert vide.corpus()[0]['titre'] == 'Guide corrigé' and vide.corpus()[0]['note'] == 'à la main'
    assert client.put('/projets/ajouts/documents/INCONNU', json=doc).status_code == 404
    m = client.put('/projets/ajouts/documents/ESSAI-GUIDE-2024', json=dict(doc, id='ESSAI-GUIDE-V2-2024')).json()
    assert m['identifiant_change'] and m['passages_retires'] == n
    e = client.get('/projets/ajouts').json()
    assert e['hors_corpus'] == [] and e['passages'] == 0 and [d['id'] for d in e['detail']] == ['ESSAI-GUIDE-V2-2024']


def test_depots_refuses(vide):
    url = '/projets/ajouts/sources'
    assert client.post(url, params={'fichier': 'a.pdf'}, content=_guide(),
                       headers={'Content-Type': 'text/plain'}).status_code == 415            # pas d'envoi par formulaire
    assert client.post(url, params={'fichier': 'faux.pdf'}, content=b'pas un pdf', headers=PDF).status_code == 422
    assert not list(vide.sources.iterdir())                                                   # rien de laissé
    assert client.post(url, params={'fichier': 'g.pdf'}, content=_guide(), headers=PDF).status_code == 201
    assert client.post(url, params={'fichier': 'G.pdf'}, content=_guide(), headers=PDF).status_code == 409
    assert client.get('/projets/ajouts/sources/..%2Fcorpus.json/profil').status_code in (404, 422)
    assert client.delete('/projets/ajouts/sources/g.pdf').status_code == 204
    assert client.delete('/projets/ajouts/sources/g.pdf').status_code == 404


def test_mesures_d_ocr_defaillant():
    from corpus_explorer.nettoyage import fragmentation, lettres_suspectes, ocr_defaillant
    sain = "La cellule de crise se réunit dès le déclenchement de l'alerte, dans une salle dédiée. " * 6
    abime = "de cer ta ines représen ta t ions par t icu l ières du processus d ' ind iv idua t ion " * 6
    assert fragmentation(sain) < 0.02 and fragmentation(abime) > 0.2
    assert lettres_suspectes('A m€.-sur€.- qu€.- l€.- trait€.-m€.-nt') >= 6 and lettres_suspectes('coûte 30 €.') == 0
    assert ocr_defaillant(abime)[0] and not ocr_defaillant(sain)[0]


def _scan(dossier):
    """PDF « scanné » : les pages du guide de test réduites à des images, sans couche de texte."""
    import pymupdf
    guide = pymupdf.open(projet.ouvrir('test').sources / 'guide.pdf')
    scan = pymupdf.open()
    for page in guide:
        pix = page.get_pixmap(dpi=200)
        nouvelle = scan.new_page(width=page.rect.width, height=page.rect.height)
        nouvelle.insert_image(nouvelle.rect, pixmap=pix)
    f = dossier / 'scan.pdf'
    scan.save(f)
    return f


def test_pdf_scanne_ocr_propose_puis_refait(vide, tmp_path):
    from corpus_explorer import ingestion, ocr
    from corpus_explorer.db import connexion, initialiser
    f = _scan(tmp_path)
    r = client.post('/projets/ajouts/sources', params={'fichier': 'scan.pdf'}, content=f.read_bytes(), headers=PDF).json()
    pr = r['profil']
    assert pr['scanne'] and pr['part_scannee'] == 1.0 and pr['proposition']['options'].get('ocr') is True
    assert any('OCR' in a for a in pr['alertes'])
    if not ocr.disponible():
        pytest.skip('ocrmypdf absent : reconnaissance non testée')
    doc = dict(id='SCAN-2024', titre='Scan', editeur='Essai', langue='fr', fichier=r['fichier'], licence='test',
               diffusion='public', extracteur='generique', options=pr['proposition']['options'])
    assert client.post('/projets/ajouts/documents', json=doc).status_code == 201
    cx = connexion(vide.db)
    initialiser(cx)
    entree = vide.corpus()[0]
    _, etat, nb, _ = ingestion.ingerer(cx, entree, p=vide)
    textes = ' '.join(t for (t,) in cx.execute("SELECT texte FROM passage WHERE statut = 'actif'"))
    assert etat == 'ingéré' and nb > 5 and 'main courante' in textes            # texte reconnu dans les images
    sig = cx.execute("SELECT extracteur FROM document").fetchone()[0]
    assert sig.endswith('· ocr') and len(list((vide.donnees / 'ocr').glob('*.pdf'))) == 1
    assert ingestion.ingerer(cx, entree, p=vide)[1] == 'inchangé'                # copie refaite gardée en cache
