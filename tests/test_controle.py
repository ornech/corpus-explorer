"""Contrôles généraux d'un corpus (corpus_explorer.controle)."""
import sqlite3

from corpus_explorer.controle import qualite


def test_projet_de_test_sans_signal(base):
    assert qualite(base) == {}


def test_signaux_detectes_sur_une_base_de_test():
    cx = sqlite3.connect(':memory:')
    cx.row_factory = sqlite3.Row
    cx.execute('CREATE TABLE passage (document_id, ordre, page, type, texte, statut)')
    lignes = [('D', 1, '10', 'texte', 'Commençons par une phrase complète et normale. Commençons encore.'),
              ('D', 2, '11', 'texte', 'Oui Oui'),                                  # faux passage
              ('D', 3, '12', 'texte', 'Texte avec un pictogramme  parasite.'),  # caractère parasite
              ('D', 4, '7', 'titre', 'Un titre daté par erreur'),                  # page qui recule
              ('D', 5, '13', 'texte', 'ommençons une seconde fois, initiale perdue.')]
    cx.executemany("INSERT INTO passage VALUES (?, ?, ?, ?, ?, 'actif')", lignes)
    r = qualite(cx)['D']
    assert len(r['erreurs']) == 2
    assert any('initiale' in a for a in r['avertissements']) and any('reculent' in a for a in r['avertissements'])
