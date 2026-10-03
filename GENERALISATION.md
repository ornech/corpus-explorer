# Généralisation : du référentiel du manuel de crise à un moteur pour tout corpus

Ce dépôt est issu (historique compris) du référentiel du manuel de crise cyber
(`/data/projets/extracteur test/referentiel`, distant git `referentiel`), qui reste en service. But : un moteur qui
découpe n'importe quel corpus de PDF en passages fidèles et sourcés, les rend interrogeables (mots, sens) et
explorables (carte, sujets), quel que soit le sujet, et qui se pilote depuis le navigateur.

Ce fichier est le journal de bord : le mettre à jour à chaque étape (fait, décidé, reste à faire).

## Fait

### 2026-10-02 — séparation (commits 0d90e8e, 5518c69)

- **Projets séparés** : un dossier par projet (`projets/<nom>/` : `projet.json`, `corpus.json`, `familles.json`,
  `synonymes.yaml`, `extracteurs/`, `sources/`, `data/`).
- **Moteur sans sujet** : paquet `corpus_explorer` ; retirés car propres à la crise (restés dans le référentiel et
  dans l'historique git) : extracteurs dédiés (ANSSI crise, NIST, Réflexes cyber, FEMA texte), graphe d'assertions
  et ses consignes, vocabulaires (supports, verbes, phases), audit du cadrage, lecture des fiches Typst, couches
  assertion → énoncé → décision du schéma. Calcul du sens dans `sens.py`, synonymes lus dans le projet.
- **Carte** adaptée à la taille du corpus ; avertissement d'export selon le champ `diffusion`.
- **Procédures** (`.claude/skills`) réécrites pour tout projet ; **tests** sur un projet synthétique.

### 2026-10-02 — interface et administration (non committé à la date d'écriture)

Décisions de l'auteur : une seule API pour tous les projets, projet dans l'adresse ; page d'administration
« état + actions » ; toutes les pages servies par l'API et reliées par un bandeau commun ; OCR intégré.

- **Projet = objet** (`projet.Projet`) passé aux fonctions ; plus d'état global. `projet.courant()` pour les
  commandes (`CORPUS_PROJET`), `projet.ouvrir(nom)` pour l'API (nom validé), `projet.creer()`.
- **API multi-projet** : routes d'un projet sous `/projets/<nom>/…` ; `/` = page des projets ; carte servie sur
  `/projets/<nom>/carte` (elle trouve l'API à partir de sa propre adresse) ; essai sur `/projets/<nom>/essai`.
- **Page des projets** (`pages/projets.html`) : état de chaque projet (`etat.py` : documents déclarés et ingérés,
  passages, fraîcheur de l'index et de la carte, sources manquantes, documents hors corpus, PDF à déclarer) ;
  actions en tâche de fond (`taches.py` : processus séparé, une à la fois par projet, journal suivi en direct) :
  tout mettre à jour, ingérer, contrôler, index de sens, carte.
- **Nouveau projet** depuis la page (titre, nom de dossier proposé, langue).
- **Ajout d'un PDF** depuis la page (`sources.py`, `profil.py`) : dépôt (corps `application/pdf`, 300 Mo au plus,
  nom normalisé), analyse du PDF et fiche pré-remplie (titre de couverture, année d'édition, langue, éditeur des
  métadonnées, identifiant proposé, extracteur, options, mentions de licence trouvées), puis tâche « ajout »
  (ingestion du document, index, carte, contrôle du document). Licence, diffusion et éditeur obligatoires.
- **PDF scannés** (`ocr.py`) : l'analyse repère un scan (images pleine page, logiciel de numérisation) et une
  couche de texte abîmée (fragments de mots > 12 %, signes collés aux lettres > 5 ‰) ; l'option `ocr` (cochée
  d'office) refait la reconnaissance avec Tesseract à l'ingestion, sur une copie en cache (`data/ocr/`), le PDF
  d'origine intact. Le contrôle de qualité signale aussi un texte d'OCR défaillant. Seuils mesurés sur les 17 PDF
  du référentiel (natifs : ≤ 6,5 % de fragments, ≤ 2,2 ‰ de signes) et sur un mémoire scanné de 2013 (29 %, 32 ‰ ;
  après OCR refait : 2 %, 1,9 ‰, 0,1 % de mots absents).
- **Modifier la fiche** d'un document déclaré (analyse du PDF refaite à l'ouverture, propositions reprenables,
  champs ajoutés à la main conservés) ; changer l'identifiant retire l'ancien document de la base puis réingère.
  **Réanalyser** un document : extraction, index, carte et contrôle.
- Script de la procédure `/ajouter-source` réduit à une enveloppe de `profil.py` (une seule logique).
- Icône d'onglet vide dans chaque page (plus de requête `favicon.ico` en 404 qui brouille les vérifications).
- Skill `interface` (conventions des pages, choix validés de la carte, vérification avec Playwright) ; CLAUDE.md
  complété (but, façon de travailler de l'auteur, environnement).

### 2026-10-03 — nettoyage de ce qui venait du manuel de crise

- **Force prescriptive retirée** de la carte (repérage des « doit », filtre « règles seulement », tri « règles
  d'abord », pastilles) : propre à un corpus de règles ; décision de l'auteur. Tri par défaut : « les plus reliés ».
- Libellés de la carte qui parlaient du « référentiel » → « projet » ; exemples de synonymes neutres.
- Pièges d'extraction (`pieges.md`) et commentaires de l'extracteur : cas décrits par la forme du document, sans
  nom de document.
- Textes des tests gardés sur la gestion de crise (décision de l'auteur, à revoir) : rôle et marche à suivre dans
  `tests/LISEZMOI.md`.

## Reste à faire

1. **Committer** le travail du 2026-10-02 (attend l'accord de l'auteur ; un commit ou un par fonction).
2. **`.venv` propre** à ce dépôt (aujourd'hui : celui du référentiel ; voir CLAUDE.md). Dépôt GitHub si l'auteur
   le souhaite (jamais de push vers le distant `referentiel`).
3. **Validation sur un corpus d'un autre sujet** : l'auteur a commencé un projet « jung » (mémoire scanné sur
   Jung) sur un serveur de démonstration dont la racine était un dossier temporaire ; à recréer dans `projets/`.
   Critères : ≤ 10 % de mots absents par document, contrôle sans erreur, sujets lisibles et partagés entre
   sources sur la carte.
4. **Petits points relevés, non traités** :
   - OCR de Tesseract : « @ » pour « ê », « ~ » pour un tiret de coupure (49 sur 26 000 mots dans le mémoire) ;
     correction possible par `remplacements` du document, pas en général (« @ » des adresses électroniques).
   - Une tâche finit « terminée » même au-delà de 10 % de mots absents (seules les erreurs de qualité donnent
     « à revoir ») : à lire dans le journal.
   - Sur un très petit corpus, un sujet de la carte peut rester sans libellé (mots partagés par tous les sujets).
   - `HF_HUB_OFFLINE=1` pour les tâches (supprime l'appel de vérification à Hugging Face) : proposé, pas décidé.
   - Fonctions de la carte peu utilisées (panier, export, comparaison, plus court chemin) : proposition de les
     ranger dans un menu « avancé », en attente de l'avis de l'auteur.
   - Textes des documents de test sur la gestion de crise (hérités) : à réécrire sur un sujet neutre plus tard,
     marche à suivre dans `tests/LISEZMOI.md` (décision de l'auteur : y revenir plus tard).
   - Pas de suppression d'un document déclaré depuis la page (retirer l'entrée de `corpus.json` à la main ; le
     document apparaît alors « hors corpus »).
5. **Reporter vers le référentiel** ce qui y servirait : profil et détection des scans, OCR, mesure de
   fragmentation dans le contrôle, icône d'onglet vide.
6. **Couche d'analyse générique** (à reconstruire, en s'inspirant du référentiel) : extraction d'assertions,
   rapprochement, audit d'un document de référence, comparaison à des documents cibles — consignes, phases,
   acteurs et vocabulaire tirés d'un `domaine.yaml` du projet ; documents cibles lus par adaptateur de format.
   Appels à un modèle payants : coût annoncé et accord avant de lancer, réponses en cache, fournisseur
   (`graphe/fournisseur.py` du référentiel) à migrer à ce moment-là.
7. **Limites connues**, selon les besoins : tableaux et schémas mal restitués, carte en fichier unique trop lourde
   au-delà d'environ 50 000 passages, rapprochement entre langues faible.

## Règles de travail

- Rien de propre à un sujet ou à un document dans `corpus_explorer/` (skill `architecture`).
- Une correction générale faite d'un côté (extraction, contrôle, carte) est reportée de l'autre
  (`git fetch referentiel` puis `git cherry-pick`, ou report à la main si les chemins diffèrent).
- Aucun ouvrage sous droits n'est versionné.
