---
name: ecrire-extracteur
description: Conventions et pièges pour écrire ou modifier un extracteur de document (découpage d'un PDF en passages fidèles et sourcés), dans corpus_explorer/extracteurs/ ou dans extracteurs/ d'un projet. À appliquer dès qu'un extracteur est créé, modifié ou débogué.
paths: "corpus_explorer/extracteurs/**, corpus_explorer/nettoyage.py, projets/*/extracteurs/**"
user-invocable: false
---

# Écrire un extracteur

Deux emplacements :
- **moteur** (`corpus_explorer/extracteurs/`) : règles valables pour tout document (`generique`, `diapositives`) ;
- **projet** (`projets/<nom>/extracteurs/`) : structure singulière d'un document ; prioritaire sur le moteur.

Une règle observée sur un document mais valable en général va dans le moteur ; une correction propre à un document
va dans les options de `corpus.json` (`remplacements`, `motifs_ignores`…) ou dans un extracteur du projet.

## Contrat (obligatoire)

```python
NOM = 'nom-court'          # identifiant stable
VERSION = '1'              # incrémenter à CHAQUE changement de sortie : force la ré-ingestion
def extraire(chemin: str, **options) -> list[dict]: ...
```

Chaque passage est un dict avec **exactement** ces clés :
`page` (numéro imprimé, str), `section`, `sous_section`, `volet` (colonne ou point de vue, ou `None`),
`ref_externe` (identifiant officiel : article, mesure…), `type` (`texte|titre|liste|note|temoignage|ligne-tableau`), `texte`.
L'ordre de la liste = ordre de lecture. L'ingestion ajoute `ordre`, `langue`, `document_id`, et écarte les faux
passages (`nettoyage.porte_du_sens`).

## Principes

- **Fidélité** : le texte d'un passage est celui de la source, nettoyé mais jamais reformulé ni traduit.
- **Traçabilité** : chaque passage doit pouvoir être retrouvé dans le PDF avec `page` + `section`.
  Préférer l'identifiant officiel (`ref_externe`) quand la source en a un.
- **Réutiliser** `generique.extraire()` pour les pages ordinaires et ne traiter à part que la structure spéciale.
- **Nettoyage** : toujours passer par `nettoyage.texte_propre()`.
- **Écarter plutôt que polluer** : en-têtes, pieds de page, sommaires, bibliographies, index, étiquettes de schéma.
  Un schéma se ressaisit à la main.
- **Général d'abord** : une règle se décrit par la forme du texte ou de la page, jamais par le nom d'un document.

## Pièges déjà rencontrés

Détail et exemples : [pieges.md](pieges.md). En bref :
- lignes d'un tableau : grouper les mots par ligne de base à ± 3 pt, jamais par `round(y)` ;
- colonnes « volets » : classer par position x relative à l'en-tête de colonne, pas au milieu de page ;
- onglets latéraux et texte vertical : à écarter avant tout ; pages à l'italienne : coordonnées remises à plat ;
- ligatures cassées, apostrophes `ˇ`, pictogrammes de la zone Unicode privée, caractères de contrôle ;
- numéro de page : pied ou en-tête **répété**, jamais une note de bas de page ; cohérence entre pages ;
- lettrines : à recoller, sinon le filtre commun les fait disparaître avec l'initiale du paragraphe.

## Vérification (obligatoire avant de conclure)

1. `python3 -m corpus_explorer.ingestion <ID>` puis `python3 -m corpus_explorer.controle` (aucune erreur).
2. Pour un changement du moteur : comparer les passages de **tous** les documents du projet avant et après ;
   seuls les documents visés doivent changer.
3. Relire au moins 15 passages répartis dans le document, en les comparant au PDF.
4. `python3 -m pytest -q tests` ; une règle nouvelle du moteur reçoit un test sur un cas synthétique.
