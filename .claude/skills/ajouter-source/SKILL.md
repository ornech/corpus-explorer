---
name: ajouter-source
description: Ajoute un document source (PDF) au projet courant de corpus-explorer — profil de mise en page, entrée corpus.json, ingestion, contrôles de complétude et de qualité, relecture. À lancer par /ajouter-source <fichier>.
argument-hint: "[chemin du fichier]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/profiler.py *) Bash(python3 -m corpus_explorer.ingestion *) Bash(python3 -m corpus_explorer.controle*) Bash(python3 -m pytest *)
---

# Ajouter une source : $ARGUMENTS

Cas courant (PDF texte ou scanné, une ou deux colonnes de lecture) : la page des projets le fait (« + Ajouter un
PDF », puis « Modifier… » / « Réanalyser » dans la liste des documents). Cette procédure sert aux cas difficiles
(extracteur propre au projet, options fines) et à la vérification approfondie (relecture comparée au PDF).
Python : celui indiqué dans CLAUDE.md (`"$PY"`) si `python3` n'a pas les dépendances.

Projet courant : variable `CORPUS_PROJET` (nom d'un dossier de `projets/`, ou chemin). Tous les fichiers ci-dessous
sont relatifs au dossier du projet. Suivre les étapes dans l'ordre ; ne pas passer à la suivante si une étape échoue.

## 1. Profiler

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/profiler.py $ARGUMENTS
```

Lire le rapport (même logique que la page : `corpus_explorer/profil.py`). Puis :
- PDF scanné (très peu de texte, ou couche de texte abîmée : fragments de mots, signes collés aux lettres) :
  option `"ocr": true` du document, proposée par le rapport (reconnaissance refaite par Tesseract à l'ingestion,
  environ 3 s par page ; ocrmypdf requis) ;
- aucune mention de licence et le document n'est pas public : demander à l'utilisateur avant d'ingérer.

## 2. Identifier le document

Renseigner à partir du document lui-même (page de garde, dernière page, métadonnées), jamais de mémoire :
titre exact, éditeur, année, version, langue (BCP-47), URL officielle si connue, licence, diffusion.
Champ inconnu → `null` (éditeur : « inconnu », la base l'exige). Ne rien inventer. Ouvrage sous droits → `diffusion` commençant par « restreint ».

Identifiant : `EDITEUR-SUJET-ANNEE` en majuscules, sans espace (ex. `OMS-RAPPORT-SANTE-2024`).
Famille : une des familles de `familles.json` (en créer une au besoin, 8 au plus).

## 3. Choisir l'extracteur

| Profil | Extracteur |
|---|---|
| Une colonne, ou deux colonnes de lecture | `generique` + options suggérées par le profileur |
| Diaporama exporté en PDF | `diapositives` |
| Structure singulière (colonnes à sens propre, tableau principal, texte brut) | extracteur du projet, dans `extracteurs/` du projet (skill `ecrire-extracteur`) |

Options utiles de `generique` : `pages_ignorees`, `remplacements`, `ligatures`, `motifs_ignores`, `titres_gras`,
`taille_corps`, `taille_section`, `garder_references`.

## 4. Déclarer et ingérer

1. Copier le fichier dans `sources/` du projet, sous un nom en minuscules avec tirets.
2. Ajouter l'entrée dans `corpus.json` (modèle : `projets/exemple/LISEZMOI.md`).
3. Lancer :

```bash
python3 -m corpus_explorer.ingestion <ID>
python3 -m corpus_explorer.controle
```

## 5. Vérifier (obligatoire)

- **Qualité** : aucune erreur au contrôle ; chaque avertissement vérifié dans le PDF.
- **Complétude** : moins de 10 % de mots absents, sinon expliquer lesquels. Les en-têtes, pieds de page,
  bibliographies et index retirés sont normaux ; du texte courant absent ne l'est pas.
- **Relecture** : afficher 15 passages tirés de trois endroits du document (début, milieu, fin) et les comparer au PDF :
  ordre de lecture, pages, sections, titres, puces, absence de fragments de schéma et de caractères parasites.
- **Recherche** : un terme caractéristique du document doit le retrouver via `GET /recherche`.
- `python3 -m pytest -q tests` doit passer.

## 6. Rendre compte

Un tableau court : ID, nombre de passages, taux d'absents, avertissements, licence, points à vérifier par l'utilisateur.
