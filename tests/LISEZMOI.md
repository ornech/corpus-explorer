# Tests de corpus-explorer

```bash
"$PY" -m pytest -q tests        # Python : voir CLAUDE.md ; ~15 s ; aucun corpus réel, aucun appel réseau payant
```

## À quoi servent ces tests

Ils vérifient le moteur de bout en bout sur un **projet synthétique** fabriqué à chaque lancement, sans dépendre
d'aucun PDF réel ni d'aucun projet de l'auteur : extraction, ingestion, contrôle, API, pages, administration,
ajout de PDF, OCR, carte. Un test qui échoue signale une régression du moteur, pas un problème de corpus.

`conftest.py` crée, dans un dossier temporaire servant de racine de projets (`CORPUS_PROJETS`), un projet `test`
(titre « Projet de test ») ingéré une fois pour toute la session (fixture `base`). Ses deux documents sont des PDF
générés avec pymupdf ; chacun porte des pièges choisis pour éprouver une règle précise :

| Document | Contenu | Ce qu'il permet de vérifier |
|---|---|---|
| `GUIDE-TEST-2024` (fr, famille « Guides ») | couverture (page ignorée), 3 pages de texte avec titres, en-tête répété, numéros de page en pied (2, 3, 4), puis une page de bibliographie | titres et sections, numéro de page lu dans le pied, en-tête répété retiré, bibliographie écartée, recherche sans accents, citation `ID, p. N`, contexte d'un passage |
| `REPORT-TEST-2023` (en, famille « Rapports ») | 3 pages de texte, en-tête répété | recherche par le sens **entre langues** (une question en français trouve une phrase anglaise), synonymes du projet (fr ↔ en), familles et couleurs de la carte |

Le projet a aussi un `synonymes.yaml` (une entrée : forme canonique, sigle, équivalent anglais) pour tester le
score lexical et `/termes-associes`.

D'autres tests fabriquent leurs propres PDF ou projets : `test_sources.py` crée un projet vide `ajouts` (dépôt,
fiche, modification, tâche d'ingestion) et un **PDF scanné** (pages du guide réduites à des images) pour l'OCR ;
`test_ingestion.py` une base temporaire pour la réconciliation des identifiants.

| Fichier | Couvre |
|---|---|
| `test_extraction.py` | pages de références (bibliographie, index) reconnues, faux passages, normalisation du texte, version du schéma de la base |
| `test_ingestion.py` | projet courant et liste des projets, sections, pages, filtres, réconciliation, extracteur du projet prioritaire |
| `test_controle.py` | contrôle de qualité : aucun signal sur le projet de test, signaux détectés sur une base piégée |
| `test_api.py` | API multi-projet : recherche par mot et par le sens, contexte, synonymes, évaluations, pages et liens, CORS, état des projets, création d'un projet, tâches de fond et journal |
| `test_sources.py` | dépôt d'un PDF, profil et fiche proposée, déclaration, refus (type, faux PDF, doublons, chemins), modification d'une fiche et changement d'identifiant, mesures d'OCR défaillant, OCR refait sur un scan (sauté si ocrmypdf manque) |
| `test_vue.py` | familles de la carte, page générée, servie par l'API, fraîcheur |

Les tests de sens chargent le modèle local e5-base ; ils sont **sautés** (pas en échec) si le modèle manque.

## Sujet des documents de test : hérité, à changer un jour

Les textes des deux documents parlent de **gestion de crise** (cellule de crise, main courante, plan de continuité
d'activité, porte-parole, retour d'expérience). Ce n'est **pas** un choix du moteur : ils viennent du projet
d'origine (référentiel du manuel de crise cyber). Le moteur n'en dépend pas ; seul le **contenu** des tests y est
lié. Décision de l'auteur (2026-10-03) : les laisser pour l'instant, y revenir plus tard.

Pour passer à un sujet neutre, réécrire `PAGES_GUIDE`, `PAGES_REPORT` et `synonymes.yaml` dans `conftest.py` en
gardant **la même structure** (3 pages de 3-4 phrases par document, titres numérotés côté guide, une phrase
française et une phrase anglaise qui disent la même chose sans mot commun, un sigle dans les synonymes), puis
adapter les assertions qui citent le contenu :

| Fichier | Ce qui dépend du sujet |
|---|---|
| `test_ingestion.py` | `LIKE 'Le plan de continuité%'` (page 3, section « 2. Continuité des activités ») ; en-têtes « Guide de test — gestion de crise », « Test report on business continuity » |
| `test_api.py` | recherches `continuite activite`, `porte-parole`, `main courante` ; synonymes `tester le PCA` → « plan de continuité d'activité » / « business continuity plan » ; recherche par le sens « qui parle aux journalistes ? » → `porte-parole` ou `spokesperson` |
| `test_extraction.py` | phrase « La cellule de crise se réunit… » |
| `test_sources.py` | phrase saine des mesures d'OCR ; « main courante » attendu dans le texte reconnu du scan |

Les identifiants (`GUIDE-TEST-2024`, `REPORT-TEST-2023`), les familles (« Guides », « Rapports ») et le titre
« Projet de test » sont neutres : les garder évite de toucher aux autres assertions.
