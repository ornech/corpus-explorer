"""Projet de test synthétique : de petits PDF générés à la volée, sans dépendre d'aucun corpus réel.
Rôle de chaque document, ce que chaque test vérifie, et sujet des textes (hérité, à changer) : tests/LISEZMOI.md.

Le projet « test » est créé dans une racine de projets temporaire (CORPUS_PROJETS), qui sert aussi de projet
courant (CORPUS_PROJET) aux commandes d'administration.
Documents :
    GUIDE-TEST-2024  (fr) couverture, 3 pages de texte avec titres, en-tête répété, numéros de page en pied,
                     puis une page de bibliographie (à écarter) ;
    REPORT-TEST-2023 (en) 3 pages de texte.
"""
import json
import os
import tempfile
from pathlib import Path

import pymupdf
import pytest

RACINE_PROJETS = Path(tempfile.mkdtemp(prefix='corpus-explorer-test-'))
DOSSIER = RACINE_PROJETS / 'test'
os.environ['CORPUS_PROJETS'] = str(RACINE_PROJETS)
os.environ['CORPUS_PROJET'] = 'test'

PAGES_GUIDE = [
    ('1. Organisation de la cellule', [
        "La cellule de crise se réunit dès le déclenchement de l'alerte, dans une salle dédiée.",
        "Le pilote de crise désigne un secrétaire qui tient la main courante pendant toute la durée de la crise.",
        "Chaque décision est horodatée et consignée, avec le nom de son auteur et les éléments qui la fondent.",
        "Les membres de la cellule disposent d'un annuaire de crise, tenu à jour et accessible hors ligne.",
    ]),
    ('2. Continuité des activités', [
        "Le plan de continuité d'activité doit être testé au moins une fois par an au cours d'un exercice.",
        "Les activités essentielles sont identifiées à l'avance, avec leur durée maximale d'interruption admissible.",
        "Les ressources critiques sont recensées : personnes, locaux, systèmes d'information et prestataires.",
        "Un mode dégradé est prévu pour chaque activité essentielle, sur papier si nécessaire.",
    ]),
    ('3. Communication', [
        "Un porte-parole unique est désigné ; il est le seul à s'exprimer auprès de la presse.",
        "Les messages destinés au public sont préparés à l'avance et validés avant toute diffusion.",
        "La communication interne informe régulièrement les salariés de l'évolution de la situation.",
        "Les échanges avec les autorités sont tracés dans la main courante, avec leur horodatage.",
    ]),
]
BIBLIOGRAPHIE = [f"AUTEUR{k}, Jean, 19{70 + k} : « Un ouvrage de référence », Éditeur, Paris." for k in range(14)]
PAGES_REPORT = [
    ('Business continuity', [
        "The business continuity plan must be exercised at least once a year by the organisation.",
        "Essential activities are identified in advance, together with their maximum tolerable downtime.",
        "A degraded mode is planned for each essential activity, including paper-based procedures.",
    ]),
    ('Crisis communication', [
        "A single spokesperson is appointed and is the only person allowed to speak to the press.",
        "Public messages are prepared in advance and approved before any release.",
        "Exchanges with the authorities are recorded in the crisis log, with a timestamp.",
    ]),
    ('Lessons learned', [
        "A debriefing is held after the crisis to identify what worked and what must be improved.",
        "Improvement actions are assigned to an owner and followed up until they are completed.",
        "The crisis log is archived together with the debriefing report.",
    ]),
]


def _page(doc, titre, paragraphes, numero=None, entete=None):
    p = doc.new_page(width=595, height=842)
    if entete:
        p.insert_text((60, 40), entete, fontsize=8, fontname='helv')
    p.insert_text((60, 120), titre, fontsize=18, fontname='hebo')
    y = 160
    for t in paragraphes:
        rect = pymupdf.Rect(60, y, 535, y + 70)
        p.insert_textbox(rect, t, fontsize=10, fontname='helv')
        y += 80
    if numero is not None:
        p.insert_text((290, 815), str(numero), fontsize=8, fontname='helv')


def _creer_projet():
    (DOSSIER / 'sources').mkdir(parents=True, exist_ok=True)
    guide = pymupdf.open()
    couverture = guide.new_page(width=595, height=842)
    couverture.insert_text((60, 300), 'Guide de test', fontsize=30, fontname='hebo')
    for k, (titre, paras) in enumerate(PAGES_GUIDE, 2):
        _page(guide, titre, paras, numero=k, entete='Guide de test — gestion de crise')
    biblio = guide.new_page(width=595, height=842)
    biblio.insert_text((60, 80), 'Bibliographie', fontsize=18, fontname='hebo')
    for k, l in enumerate(BIBLIOGRAPHIE):
        biblio.insert_text((60, 120 + 22 * k), l, fontsize=9, fontname='helv')
    guide.save(DOSSIER / 'sources' / 'guide.pdf')
    report = pymupdf.open()
    for k, (titre, paras) in enumerate(PAGES_REPORT, 1):
        _page(report, titre, paras, numero=k, entete='Test report on business continuity')
    report.save(DOSSIER / 'sources' / 'report.pdf')
    commun = dict(licence='test', diffusion='public', extracteur='generique')
    (DOSSIER / 'corpus.json').write_text(json.dumps([
        dict(id='GUIDE-TEST-2024', titre='Guide de test', editeur='Essai', annee=2024, langue='fr',
             fichier='sources/guide.pdf', famille='Guides', options=dict(pages_ignorees=[0]), **commun),
        dict(id='REPORT-TEST-2023', titre='Test report', editeur='Test', annee=2023, langue='en',
             fichier='sources/report.pdf', famille='Rapports', options={}, **commun),
    ], ensure_ascii=False), encoding='utf-8')
    (DOSSIER / 'familles.json').write_text(json.dumps({'familles': ['Guides', 'Rapports']}), encoding='utf-8')
    (DOSSIER / 'projet.json').write_text(json.dumps({'titre': 'Projet de test'}), encoding='utf-8')
    (DOSSIER / 'synonymes.yaml').write_text("plan de continuité d'activité: [PCA, business continuity plan]\n",
                                            encoding='utf-8')


_creer_projet()


@pytest.fixture(scope='session')
def base():
    """Projet de test ingéré une fois pour toute la session."""
    from corpus_explorer import ingestion
    from corpus_explorer.db import connexion
    ingestion.main([])
    return connexion()
