# Projet d'exemple

Seul ce modèle est versionné avec le moteur ; les autres dossiers de `projets/` restent hors git.

Modèle de projet : copier ce dossier sous `projets/<nom>/` (minuscules, chiffres, tirets). Il apparaît sur la page
des projets de l'API ; en ligne de commande, le choisir avec `CORPUS_PROJET=<nom>`.

| Fichier | Rôle |
|---|---|
| `projet.json` | titre du projet (API, carte), langue principale |
| `corpus.json` | liste des documents (voir l'entrée type ci-dessous) |
| `familles.json` | familles de documents, dans l'ordre d'affichage (couleurs de la carte) — facultatif |
| `synonymes.yaml` | formes équivalentes d'un terme pour la recherche par le sens — facultatif |
| `extracteurs/` | extracteurs propres au projet, prioritaires sur ceux du moteur — facultatif |
| `sources/` | fichiers sources (hors git) |
| `data/` | base, index, carte : reconstruits par les commandes, hors git |

Entrée type de `corpus.json` (champs inconnus : `null`, ne rien inventer) :

```json
{
  "id": "EDITEUR-SUJET-ANNEE",
  "titre": "Titre exact du document",
  "editeur": "Éditeur",
  "annee": 2024,
  "version": null,
  "langue": "fr",
  "url": null,
  "fichier": "sources/editeur-sujet-annee.pdf",
  "licence": "Licence lue dans le document",
  "diffusion": "public",
  "famille": "Nom de famille (voir familles.json)",
  "extracteur": "generique",
  "options": { "pages_ignorees": [0] }
}
```

`options.ocr: true` : PDF scanné ; la reconnaissance de caractères est refaite à l'ingestion (Tesseract, via
ocrmypdf), sur une copie gardée dans `data/ocr/` ; le PDF d'origine reste intact.

`diffusion` commençant par « restreint » : l'export des passages rappelle de ne pas diffuser les extraits.

`synonymes.yaml` :

```yaml
changement climatique: [réchauffement climatique, climate change]
OMS: [Organisation mondiale de la santé, WHO]
```
