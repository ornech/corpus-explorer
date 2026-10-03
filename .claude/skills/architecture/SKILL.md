---
name: architecture
description: Invariants de corpus-explorer — projets, couches de données, conventions de l'API FastAPI, schéma et compatibilité SQLite. À appliquer avant toute modification du schéma, de l'API, de l'ingestion, de la carte ou des tests.
paths: "corpus_explorer/*.py, corpus_explorer/schema.sql, corpus_explorer/pages/**, tests/**, projets/**"
user-invocable: false
---

# Architecture de corpus-explorer

```
projets/<nom>/  (corpus.json, familles.json, synonymes.yaml, sources/, data/)
      │  commandes : CORPUS_PROJET=<nom>   ·   API : /projets/<nom>/…   ·   tâches de fond (taches.py)
      ▼
ingestion ──▶ SQLite (<projet>/data/corpus.db) ◀── API FastAPI (corpus_explorer/api.py) ◀── pages, outils
                    │
                    └──▶ index de sens (<projet>/data/index-semantique) ──▶ carte (<projet>/data/passages-3d.html)

Pages servies par l'API : /  (projets et administration) · /projets/<nom>/carte · /projets/<nom>/essai · /docs
```

## Modules (`corpus_explorer/`)

| Module | Rôle |
|---|---|
| `projet.py` | `Projet` (chemins d'un projet), `lister`, `ouvrir` (nom validé), `creer`, `courant` (`CORPUS_PROJET`) |
| `db.py`, `schema.sql` | base SQLite d'un projet : `document`, `passage`, `passage_fts` (trigram) |
| `extracteurs/` | `generique` (PDF), `diapositives` (diaporamas) ; ceux d'un projet sont prioritaires |
| `nettoyage.py` | texte propre, normalisation, filtre des faux passages, mesures d'OCR défaillant |
| `ingestion.py` | extraction → réconciliation (identifiants stables) ; option `ocr` ; `retirer_document` |
| `ocr.py` | reconnaissance refaite par Tesseract (ocrmypdf), copie en cache dans `data/ocr/` |
| `controle.py` | complétude (mots de la source absents des passages) et qualité (signaux par document) |
| `profil.py` | profil d'un PDF et fiche proposée (page d'ajout et procédure `/ajouter-source`) |
| `sources.py` | dépôt d'un PDF, déclaration et modification d'une fiche dans `corpus.json` |
| `sens.py`, `semantique.py` | modèle de sens local (e5-base) + score lexical ; index de sens d'un projet |
| `vue_passages.py` | carte 3D (page autonome, gabarit dans une chaîne Python : skill `interface`) |
| `etat.py`, `taches.py` | état d'un projet pour la page ; actions d'administration en tâche de fond |
| `api.py` | FastAPI : tous les projets, pages, administration |
| `pages/` | page des projets, essai de pertinence, carte absente |

## Invariants — ne jamais enfreindre

1. **Le moteur ne connaît aucun sujet.** Rien de propre à un domaine, à un document ou à un corpus dans
   `corpus_explorer/` : ce qui l'est va dans le projet (configuration, options, extracteurs du projet).
2. **Un projet = un dossier.** Chemins tirés d'un objet `projet.Projet` passé aux fonctions (`projet.courant()`
   pour les commandes, `projet.ouvrir(nom)` pour l'API) ; aucun état global propre à un projet, aucun chemin absolu.
   Un nom de projet venu d'une adresse est validé (`NOM_VALIDE`), jamais pris comme chemin.
3. **Seuls l'API et les commandes d'administration ouvrent la base.**
4. **Fidélité et traçabilité** : un passage est le texte de la source, jamais reformulé ; il porte document, page
   (ou `ref_externe`) et se cite `ID, p. N`.
5. **Ré-ingestion** : un passage au texte inchangé garde son identifiant (empreinte) ; voir `ingestion.reconcilier`.
6. **Couches à venir** (analyse) : elles s'ajoutent au-dessus des passages sans les réécrire ; ce qu'un modèle
   produit naît « à vérifier » et cite des passages dont l'existence est vérifiée en base.

## Compatibilité (machine cible : Ubuntu 22.04, Python 3.10, SQLite 3.37)

- Rien qui exige Python ≥ 3.11 : ni `tomllib`, ni `except*` / `ExceptionGroup`, ni `typing.Self`.
- SQLite ≥ 3.34 : FTS5 `tokenize='trigram'` **sans option**. Accents et casse : `nettoyage.normaliser()`
  appliqué au texte indexé (ingestion) et à la requête (API). Pas de trigger sur `passage_fts`.
- Commandes : `python3` (pas `python`).

## Modifier le schéma

1. Modifier `corpus_explorer/schema.sql` (instructions `IF NOT EXISTS`).
2. Incrémenter `PRAGMA user_version` dans le schéma **et** `VERSION_SCHEMA` dans `db.py`.
3. Base sans donnée saisie à la main : la reconstruire (supprimer `<projet>/data/corpus.db`, puis ingestion).
   Sinon : script de migration, jamais de suppression.

## Conventions de l'API

- Un modèle Pydantic par réponse ; tout passage renvoyé porte `citation`.
- Erreurs en français, codes HTTP explicites (404 inconnu, 422 saisie invalide, 503 index absent).
- Recherche : passer par `_requete_fts()` ; jamais de saisie utilisateur concaténée dans du SQL.
- Routes d'un projet sur le routeur `pr` (`/projets/{nom}`), projet obtenu par `Depends(projet_de)`.
- Lecture seule depuis une page locale (CORS GET pour l'origine « null » et localhost). Une écriture (POST) prend un
  corps JSON validé par Pydantic : un formulaire d'un autre site ne peut pas la déclencher.
- Tâche longue (ingestion, index, carte) : `taches.lancer()` ; elle exécute la commande du moteur dans un processus
  séparé, une tâche à la fois par projet, journal dans `<projet>/data/taches/`.
- Ajout d'un PDF : corps brut `application/pdf` (pas de formulaire multipart, rien à installer ; un autre site ne
  peut pas l'envoyer), nom de fichier normalisé (`sources.nom_de_fichier`), puis déclaration validée par
  `NouveauDocument` (licence et diffusion obligatoires, jamais de valeur par défaut) ; profil : `profil.py`, partagé
  avec la procédure `/ajouter-source`.
- Pages : bandeau `nav.site` commun (Projets › projet · Carte · Essai · API) ; dans une page d'un projet, adresses de
  l'API relatives (`fetch('recherche?…')`), pour qu'elle serve le projet de son adresse.
- Chaque nouveau point d'entrée a au moins un test dans `tests/`, sur le projet de test synthétique (`tests/conftest.py`).

## Vérification

`"$PY" -m pytest -q tests` avant de conclure (Python : voir CLAUDE.md). Après un changement d'extraction : ingérer un
projet réel et lancer `"$PY" -m corpus_explorer.controle`. Après un changement de page : skill `interface`.
