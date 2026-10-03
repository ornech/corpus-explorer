# corpus-explorer — moteur de corpus documentaire, indépendant du sujet

## But

Prendre n'importe quel ensemble de PDF (rapports, guides, mémoires, normes…), les découper en **passages fidèles
et sourcés** (texte exact de la source, document, page, section), puis permettre :
- de **chercher** par mot exact ou **par le sens** (même sans mot commun, français et anglais mêlés) ;
- d'**explorer** le corpus sur une **carte 3D** où la position dit de quoi parle un passage, regroupée en sujets ;
- de tout faire **depuis le navigateur** : créer un projet, ajouter un PDF, corriger une fiche, relancer les
  traitements, suivre leur journal.

Chaque passage se cite `ID, p. N` et se retrouve dans le PDF. Rien n'est reformulé ni inventé : c'est la règle
première, au-dessus de toute commodité.

Origine : extrait (historique git compris) du référentiel du manuel de crise cyber,
`/data/projets/extracteur test/referentiel`, qui reste en service pour ce manuel. Ici, **aucun sujet n'est
codé** : ce qui est propre à un corpus vit dans son dossier de projet.

État, décisions et reste à faire : **GENERALISATION.md** (à tenir à jour à chaque étape). Organisation et
utilisation : README.md.

## L'auteur et sa façon de travailler (à respecter)

- **Français partout** : code, messages, pages, documentation, commits.
- **Décisions par questions** : quand un choix revient à l'auteur, le poser avec l'outil de questions à options
  (2 à 4 options, la recommandée en tête avec « (Recommandé) », conséquences concrètes), pas en liste à la fin
  d'un message. Avancer seul sur ce qui a un choix par défaut évident.
- **Prendre du recul** : devant un résultat étrange, vérifier d'abord la mesure et sa référence (comparer à sujet
  égal, chercher l'explication simple) avant de proposer un remède lourd ou payant. Pas de jargon mathématique.
- **Vérifier avant de conclure** : tests, puis essai réel (API, pages vues avec un navigateur sans interface,
  skill `interface`). Dire franchement ce qui n'a pas été vérifié.
- **Dire où l'on travaille** : quel dépôt, quel projet, quel serveur ; l'auteur alterne entre le référentiel et
  ce dépôt.
- **Ne rien committer ni pousser sans demande explicite.** Le distant git `referentiel` est la source d'origine :
  **ne jamais y pousser** ce dépôt. Pas encore de dépôt GitHub propre (à créer si l'auteur le demande).
- **Droits d'auteur** : aucun ouvrage sous droits n'est versionné ni copié hors de son projet ; un document sous
  droits a `diffusion: "restreint"` (rappel à chaque export d'extraits). Licence et diffusion ne reçoivent jamais
  de valeur par défaut.
- **Appels payants** : le moteur n'appelle aucun modèle distant (pas de clé, pas de coût). Toute future couche
  qui en appellerait un : coût annoncé et accord de l'auteur avant de lancer, réponses gardées en cache. Clés
  d'API dans `~/.config/anthropic/cle` (chmod 600), jamais dans le dépôt ni dans un message.
- **Généraliser** : une correction se décrit par la forme du texte ou de la page, jamais par le nom d'un document
  (voir skill `ecrire-extracteur`).

## Commandes

Python : en attendant le `.venv` propre à ce dépôt (à créer : `python3 -m venv .venv && .venv/bin/pip install -e
'.[test]'`, plusieurs Go à cause de torch), utiliser celui du référentiel, qui a toutes les dépendances :

```bash
PY="/data/projets/extracteur test/referentiel/.venv/bin/python3"
"$PY" -m uvicorn corpus_explorer.api:app --port 8765   # http://localhost:8765/ : projets, administration, pages
"$PY" -m pytest -q tests                               # projet synthétique, sans corpus réel (~15 s)
# Commandes d'administration (aussi lancées depuis la page des projets, en tâche de fond) :
export CORPUS_PROJET=<nom>                             # projet courant : projets/<nom>/ (ou un chemin)
"$PY" -m corpus_explorer.ingestion [ID…]               # IDs donnés : réingérés même inchangés
"$PY" -m corpus_explorer.controle [--qualite] [ID…]    # complétude et qualité
"$PY" -m corpus_explorer.semantique                    # index de sens
"$PY" -m corpus_explorer.vue_passages                  # carte → <projet>/data/passages-3d.html
"$PY" -m corpus_explorer.profil <fichier.pdf>          # profil d'un PDF avant ajout
```

Le port 8765 est souvent pris par l'API du référentiel : prendre un autre port (8766…) au besoin.
`CORPUS_PROJETS=<dossier>` change la racine des projets (tests, démonstrations hors dépôt) : un projet créé sur un
serveur lancé ainsi vit dans ce dossier, pas dans `projets/`.

## Faits

- Le moteur (`corpus_explorer/`) ne contient rien de propre à un sujet ou à un document : ce qui l'est va dans le
  projet (`corpus.json`, options, `extracteurs/` du projet). Règle à tenir à chaque modification (skill `architecture`).
- Une correction générale faite ici ou dans le référentiel (extraction, contrôle, carte) est reportée de l'autre
  côté (`git fetch referentiel` puis `git cherry-pick`, ou à la main : les chemins diffèrent).
- Machine de l'auteur : Ubuntu 22.04, Python 3.10, SQLite 3.37, pas de GPU. Outils système présents :
  `ocrmypdf` + `tesseract` (fra, eng), `google-chrome`, `brave-browser`, `node` ; Playwright installé pour le
  Python système (`~/.local`), utilisable avec `executable_path='/usr/bin/google-chrome'`.
- Modèle de sens `intfloat/multilingual-e5-base`, local, sur processeur, dans `~/.cache/huggingface`.
  L'avertissement « unauthenticated requests to the HF Hub » vient de Hugging Face (vérification de version du
  modèle), **pas** de Claude ; `HF_HUB_OFFLINE=1` le supprime (proposé, pas appliqué).
- **Les projets de l'auteur sont hors du dépôt** (`.gitignore` : `projets/*` sauf `projets/exemple/`, décision du
  2026-10-03) ; un projet à partager aurait son propre dépôt git dans son dossier. `sources/` et `data/` sont
  hors git partout ; `data/` se reconstruit entièrement (base, index, carte,
  copies OCR, journaux des tâches), sauf `data/evaluations.jsonl` (jugements saisis à la main sur l'essai).
- `projets/exemple/` est le modèle de projet (corpus vide) ; les projets réels se créent depuis la page des projets.
- Skills du projet : `ajouter-source` (/ajouter-source <fichier>, cas difficiles), `ecrire-extracteur`,
  `architecture`, `interface` (chargés selon les fichiers modifiés).
