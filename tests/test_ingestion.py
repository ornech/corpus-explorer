"""Ingestion d'un projet : extraction générique, filtres communs, réconciliation des identifiants."""
import pytest

from corpus_explorer import projet
from corpus_explorer.db import connexion, initialiser
from corpus_explorer.ingestion import charger_extracteur, reconcilier


def _textes(cx, doc):
    return [r[0] for r in cx.execute("SELECT texte FROM passage WHERE document_id = ? AND statut = 'actif' ORDER BY ordre", (doc,))]


def test_projet_courant_et_liste():
    p = projet.courant()
    assert p.nom == 'test' and p.titre() == 'Projet de test'
    assert [e['id'] for e in p.corpus()] == ['GUIDE-TEST-2024', 'REPORT-TEST-2023']
    assert [x.nom for x in projet.lister()] == ['test'] and projet.ouvrir('test').dossier == p.dossier
    for nom in ('inconnu', '../test', 'Test', ''):
        with pytest.raises(LookupError):
            projet.ouvrir(nom)


def test_titres_sections_et_numeros_de_page(base):
    r = base.execute("SELECT page, section, type FROM passage WHERE texte LIKE 'Le plan de continuité%'").fetchone()
    assert tuple(r) == ('3', '2. Continuité des activités', 'texte')            # numéro lu en pied de page
    assert base.execute("SELECT type FROM passage WHERE texte = '3. Communication'").fetchone()[0] == 'titre'


def test_entetes_couverture_et_bibliographie_ecartes(base):
    guide = ' '.join(_textes(base, 'GUIDE-TEST-2024'))
    assert 'Guide de test — gestion de crise' not in guide       # en-tête répété
    assert 'AUTEUR3' not in guide and 'Bibliographie' not in guide  # page de références reconnue à son contenu
    assert 'Test report on business continuity' not in ' '.join(_textes(base, 'REPORT-TEST-2023'))


def test_reingestion_garde_les_identifiants(base):
    from corpus_explorer import ingestion
    avant = {r[0]: r[1] for r in base.execute('SELECT texte, id FROM passage')}
    ingestion.main(['GUIDE-TEST-2024'])                            # forcée : document réextrait
    apres = {r[0]: r[1] for r in connexion().execute('SELECT texte, id FROM passage')}
    assert apres == avant


def test_extracteur_du_projet_prioritaire(tmp_path):
    (tmp_path / 'propre.py').write_text("NOM = 'propre'\nVERSION = '1'\ndef extraire(chemin, **_):\n    return []\n")
    p = projet.courant()
    p.extracteurs = tmp_path
    assert charger_extracteur('propre', p).NOM == 'propre'
    assert charger_extracteur('generique', p).NOM == 'generique'   # sinon, celui du moteur


@pytest.fixture
def cx(tmp_path):
    cx = connexion(tmp_path / 'essai.db')
    initialiser(cx)
    cx.execute("INSERT INTO document (id, titre, editeur, langue, fichier, sha256, extracteur) "
               "VALUES ('D', 'Essai', 'Essai', 'fr', 'd.pdf', 'x', 'essai v1')")
    return cx


def _p(texte, volet=None, page='1'):
    return dict(texte=texte, volet=volet, page=page, section='S', sous_section=None, ref_externe=None, type='texte')


def _ids(cx):
    return {r['texte']: r['id'] for r in cx.execute("SELECT id, texte FROM passage WHERE statut = 'actif'")}


def test_texte_inchange_garde_son_identifiant_meme_deplace(cx):
    reconcilier(cx, 'D', 'fr', [_p('Ouvrir le registre.'), _p('Alimenter le registre.')])
    avant = _ids(cx)
    bilan = reconcilier(cx, 'D', 'fr', [_p('Titre ajouté.'), _p('Alimenter le registre.', page='2'), _p('Ouvrir le registre.')])
    assert _ids(cx)['Ouvrir le registre.'] == avant['Ouvrir le registre.']
    assert _ids(cx)['Alimenter le registre.'] == avant['Alimenter le registre.']
    assert bilan == dict(conserves=2, nouveaux=1, supprimes=0)
    assert cx.execute("SELECT page, ordre FROM passage WHERE texte = 'Alimenter le registre.'").fetchone()[:] == ('2', 2)


def test_doublons_distingues_par_volet_et_passage_disparu_supprime(cx):
    reconcilier(cx, 'D', 'fr', [_p('Même phrase.', 'gauche'), _p('Même phrase.', 'droite'), _p('Disparaîtra.')])
    avant = {r['volet']: r['id'] for r in cx.execute("SELECT id, volet FROM passage WHERE volet IS NOT NULL")}
    bilan = reconcilier(cx, 'D', 'fr', [_p('Même phrase.', 'droite'), _p('Même phrase.', 'gauche')])
    assert {r['volet']: r['id'] for r in cx.execute("SELECT id, volet FROM passage WHERE volet IS NOT NULL")} == avant
    assert bilan['supprimes'] == 1 and 'Disparaîtra.' not in _ids(cx)
