# corpus-explorer

Moteur de corpus documentaire, indépendant du sujet. Il découpe des PDF en **passages fidèles et sourcés**
(document, page, section), les rend interrogeables **par mot et par le sens**, et les rend explorables sur une
**carte 3D** où la position dit de quoi parle un passage.

Issu du référentiel du manuel de crise cyber (`/data/projets/extracteur test/referentiel`), en cours de
généralisation : voir [GENERALISATION.md](GENERALISATION.md).

## Organisation

```
corpus-explorer/
├── corpus_explorer/        le moteur (paquet Python)
│   ├── projet.py           projet courant et ses chemins
│   ├── db.py  schema.sql   base SQLite d'un projet (documents, passages, index plein texte)
│   ├── ingestion.py        extraction + réconciliation des passages (identifiants stables)
│   ├── nettoyage.py        nettoyage du texte, filtre des faux passages
│   ├── controle.py         complétude et qualité d'un corpus
│   ├── sens.py             modèle de sens (embeddings locaux) + score lexical
│   ├── semantique.py       index de sens d'un projet
│   ├── api.py              API FastAPI : tous les projets (/projets/<nom>/…), pages, administration
│   ├── etat.py  taches.py  état d'un projet ; actions d'administration en tâche de fond
│   ├── sources.py profil.py dépôt, déclaration et modification d'un PDF ; profil et fiche pré-remplie
│   ├── ocr.py              reconnaissance de caractères refaite pour les PDF scannés (Tesseract)
│   ├── vue_passages.py     carte 3D des passages (fichier HTML autonome)
│   ├── extracteurs/        generique (PDF), diapositives (diaporamas)
│   └── pages/              projets (accueil et administration), essai de pertinence
├── projets/
│   └── exemple/            modèle de projet (voir LISEZMOI.md)
├── tests/                  tests sur un projet synthétique généré à la volée
└── .claude/skills/         procédures : ajouter une source, écrire un extracteur, architecture
```

Un **projet** est un dossier `projets/<nom>/` : `corpus.json` (documents), `familles.json` (familles et couleurs),
`synonymes.yaml` (facultatif), `extracteurs/` (facultatif), `sources/` et `data/`. Seul le modèle `projets/exemple/`
est versionné avec le moteur : les projets créés restent sur la machine (un projet à partager a son propre dépôt).

## Installation

Ubuntu 22.04, Python 3.10, SQLite ≥ 3.34.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
```

Le modèle de sens (`intfloat/multilingual-e5-base`) est téléchargé au premier usage puis gardé en cache.

PDF scannés (option `ocr` d'un document) : `sudo apt install ocrmypdf tesseract-ocr-fra` (autres langues :
`tesseract-ocr-<code>`). La reconnaissance est refaite à l'ingestion, sur une copie gardée dans `data/ocr/`.

## Utilisation

```bash
python3 -m uvicorn corpus_explorer.api:app --port 8765
```
<img width="1865" height="890" alt="image" src="https://github.com/user-attachments/assets/3dada512-fe65-4b99-b9b5-13ac36203438" />

Puis ouvrir <http://localhost:8765/> : la page des projets donne l'état de chaque projet (documents, passages,
fraîcheur de l'index et de la carte) et lance les mises à jour en tâche de fond (« Tout mettre à jour » :
ingestion, index de sens, carte). Chaque page porte le même bandeau : Projets › projet · Carte · Essai · API.

| Adresse | Page |
|---|---|
| `/` | projets et administration |
| `/projets/<nom>/carte` | carte 3D des passages |
| `/projets/<nom>/essai` | essai de pertinence (mots et sens côte à côte) |
| `/docs` | documentation de l'API ; routes d'un projet sous `/projets/<nom>/…` |

Les mêmes actions en ligne de commande, sur le projet courant :

```bash
export CORPUS_PROJET=mon-projet                       # dossier projets/mon-projet (ou un chemin)
python3 -m corpus_explorer.ingestion                   # construit / met à jour la base du projet
python3 -m corpus_explorer.controle                    # complétude et qualité
python3 -m corpus_explorer.semantique                  # index de sens (quelques minutes sur processeur)
python3 -m corpus_explorer.vue_passages                # carte → projets/mon-projet/data/passages-3d.html
python3 -m pytest -q tests
```

Nouveau projet : bouton « + Nouveau projet » de la page des projets. Nouvelle source : bouton « + Ajouter un PDF »
du projet. Le PDF est analysé, la fiche du document est pré-remplie et doit être vérifiée (licence et diffusion
sont à saisir), puis l'ingestion, l'index, la carte et le contrôle du document s'enchaînent. Cas difficiles
(tableaux, colonnes à sens propre) : procédure `/ajouter-source` dans Claude Code. Un PDF scanné, sans texte ou
au texte abîmé, est détecté à l'ajout : l'option « refaire l'OCR » est cochée d'office.

Dans la liste des documents d'un projet : « Modifier… » corrige la fiche (titre, auteur, licence, diffusion,
options, identifiant) après avoir refait l'analyse du PDF, puis réingère ; « Réanalyser » réextrait le document
(index, carte et contrôle compris). Changer l'identifiant change les citations « ID, p. N ».
