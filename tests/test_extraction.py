"""Règles générales d'extraction et de nettoyage, sur des cas synthétiques."""
import sqlite3

import pytest

from corpus_explorer.db import VERSION_SCHEMA, connexion, initialiser
from corpus_explorer.extracteurs.generique import page_de_references
from corpus_explorer.nettoyage import normaliser, porte_du_sens


def test_pages_de_references_reconnues_a_leur_contenu():
    index = '\n'.join(['Index des noms cités'] + [f'Nom{k}, Prénom  {k}; {k + 12}; {k + 40}' for k in range(12)])
    biblio = '\n'.join(['Bibliographie'] + [f"AUTEUR{k}, Jean, 19{60 + k} : « Un titre d'ouvrage », Éditeur, Paris." for k in range(12)])
    texte = '\n'.join(["La cellule de crise se réunit dès le déclenchement de l'alerte."] * 12)
    assert page_de_references(index) and page_de_references(biblio) and not page_de_references(texte)


@pytest.mark.parametrize('texte, attendu', [('________', False), ('(a) (b)', False), ('Oui Non', False), ('9h00 à 9h30', False),
                                            ('C', False), ('Annuaire', True), ('Le registre doit être tenu.', True)])
def test_faux_passages(texte, attendu):
    assert porte_du_sens(texte) is attendu


def test_normaliser():
    assert normaliser('Œuvre des ÉQUIPES') == 'oeuvre des equipes'


def test_base_ancienne_refusee(tmp_path):
    cx = connexion(tmp_path / 'vieille.db')
    cx.execute('CREATE TABLE passage (id INTEGER)')
    cx.execute('PRAGMA user_version = 99')
    with pytest.raises(RuntimeError, match='supprimer'):
        initialiser(cx)


def test_base_neuve_a_la_bonne_version_et_index_sans_option(tmp_path):
    cx = connexion(tmp_path / 'neuve.db')
    initialiser(cx)
    assert cx.execute('PRAGMA user_version').fetchone()[0] == VERSION_SCHEMA
    sql = cx.execute("SELECT sql FROM sqlite_master WHERE name='passage_fts'").fetchone()[0]
    assert "tokenize = 'trigram')" in sql      # aucune option : compatible SQLite 3.34+
