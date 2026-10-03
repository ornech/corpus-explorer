# Pièges d'extraction déjà rencontrés

> Chaque cas est décrit par la **forme** du document qui l'a révélé, jamais par son nom : la règle vaut pour tout
> document de même forme. Les cas « extracteur dédié » (colonnes à sens propre, tableau principal) n'ont pas
> d'extracteur dans le moteur : ils se traitent par un extracteur du projet (`projets/<nom>/extracteurs/`).

## Tableau des cas

| Symptôme | Forme du document | Cause | Correction |
|---|---|---|---|
| Deux phrases identiques à la suite, impossible de savoir à qui elles s'adressent | guide en deux colonnes qui sont deux points de vue (ex. « volet A » / « volet B ») | Colonnes fusionnées par l'extraction en texte brut | Extracteur du projet : lire les blocs avec leur position (`get_text('blocks')`) ; colonne = position x relative au bord gauche de l'en-tête de colonne (± 20 pt). Bloc qui couvre les deux colonnes → `commun`. |
| Colonne mal attribuée pour une ligne courte | même forme | Seuil calculé sur le milieu de page | Seuil sur l'en-tête de colonne, pas sur le milieu. |
| Première ligne d'une cellule rattachée à l'élément précédent | document dont le contenu principal est un tableau (identifiant, texte, priorité…) | Lignes groupées par `round(y)` : l'identifiant et le texte ont des lignes de base décalées de 1 pt | Grouper en « rangées visuelles » (écart de ligne de base < 3 pt), puis répartir par colonne. |
| Étiquette (« R2 ») placée après son propre texte | même forme | Étiquette en gras, ligne de base différente | Même correction : rangées visuelles, tri par x dans la rangée. |
| En-tête de tableau introuvable | même forme | En-tête plus bas sur la première page du tableau | Chercher un mot de l'en-tête n'importe où dans la page et prendre les mots de la même ligne. |
| Numéros 1, 2, 3, 4 pris pour des numéros de page et des titres | guide à onglets de navigation latéraux | Onglets dans la marge droite | Écarter les blocs à x > 90 % de la largeur et le texte vertical (largeur < 12 pt). |
| « défi nition », « fl ux » | PDF à police mal encodée | Ligature suivie d'une espace | Option `ligatures: true`. |
| « lˇorganisation », « cSur », « Suvre », « € » parasites | PDF à encodage défectueux | Caractères mal encodés | `remplacements` dans corpus.json (propres au document). |
| Page répétée, parfois tronquée | recueil de fiches d'une page | Maquette | Dédoublonnage par inclusion du texte normalisé. |
| ``, `\x07` en début de puce | guide à pictogrammes | Pictogrammes (zone Unicode privée) et caractères de contrôle | Supprimés par `texte_propre()`. |
| Mots en capitales isolés (« ÉTAPE », « PHASE ») | guide à schémas | Étiquettes de schéma à la taille du corps | Blocs < 40 caractères sans minuscule écartés. |
| « October I 0, 20 17 » | fichier texte issu d'une reconnaissance de caractères | OCR ancien | Ne pas extraire du .txt : obtenir le PDF d'origine (option `ocr` si c'est un scan). |
| « m€.-sur€.- », « cer ta ines », « .:.::.t1s.:ien.:e », lignes perdues | mémoire scanné dont la couche de texte vient d'un OCR ancien (Adobe Paper Capture) | Couche de texte abîmée : l'extraction la restitue fidèlement, défauts compris | Pas un défaut d'extracteur : option `ocr` du document (Tesseract via ocrmypdf) ; détection par `nettoyage.ocr_defaillant` (fragments de mots > 12 %, signes collés aux lettres > 5 ‰). Après OCR : « @ » pour « ê », « ~ » pour un tiret de coupure, rares. |
| Recherche en erreur « error in tokenizer constructor » | tous | Option `remove_diacritics` du tokenizer trigram absente avant SQLite 3.45 | Index en trigram simple, texte normalisé en Python (`nettoyage.normaliser`). |
| Puces et phrases courtes prises pour des titres, sections fausses | rapport dont les tableaux sont en 10 pt et le texte courant en 12 pt | Corps mesuré sur tout le PDF, pages écartées comprises | `generique` : corps mesuré sur les seules pages extraites. |
| « Abstract », « Appendix A. … » en texte courant | rapport anglais à titres en gras à la taille du corps | Titres non numérotés, même taille que le corps | Option `titres_gras=True` de `generique` (une ligne, gras, corps ; `1.1.` → sous-section). |
| Pages liminaires citées au numéro PDF | rapport à pages liminaires en chiffres romains | Numéro `i`, `ii`… dans le pied de page | `generique` lit aussi `i`, `ii`… seuls dans la marge. |
| Première rangée sous l'en-tête perdue | document à tableau principal | Filtre sur le haut du mot (`w[1]`) comparé au bas de l'en-tête | Filtrer sur la ligne de base (`w[3]`). Une ligne de tableau hors élément lève une erreur au lieu d'être ignorée. |
| Titre et introduction mêlés à la dernière ligne d'un tableau | même forme | Texte courant et second en-tête sur une page de tableau | Blocs ≥ 11,5 pt et légendes « Table N. » sortis du tableau et intercalés par position ; tous les en-têtes de la page écartés. |
| Toutes les pages citées « p. 2 » | référentiel dont le pied de page répète un titre finissant par un nombre (« … VERSION 2 ») | Le nombre du bandeau écrasait le vrai numéro | `generique` : un nombre identique d'une page à l'autre dans un bandeau répété n'est pas un numéro de page. |
| Sections « L », « U », texte « a sécurité… » ; sections vides | guides à lettrines (grande initiale) ou à flèches décoratives | Lettrine ou flèche prise pour le plus haut niveau de titre | `generique` : lettrine recollée au paragraphe suivant ; un bloc d'un caractère n'est jamais un niveau de titre. |
| Dizaines de faux titres, 17 à 24 % de mots absents | diaporama exporté en PDF | Corps minuscule, texte éparpillé en boîtes | Extracteur `diapositives` : un passage par diapositive, lu colonne par colonne ; titre = plus grande police contenant des mots, en haut. Frises chronologiques : ordre approximatif. |

## Pages à l'italienne, titres coupés, corps minoritaire (generique v12)

- **Texte tourné de 90° dans une page droite** (glossaire et tableaux d'un référentiel) : `line['dir'] == (0, 1)`.
  Les fins de lignes verticales touchent le bas de page et passent pour des numéros de page (« Objectif 19 » →
  p. 19). `_blocs()` remet les coordonnées à plat (`bbox = (y0, W-x1, y1, W-x0)`, page paysage).
- **Titre sur deux blocs de même taille** : recollé si la suite commence par une minuscule, ou, en capitales,
  si les blocs se touchent et que la coupure tombe sur un mot-outil (« …ORGANISATION DE LA » + « RÉUNION
  ANNUELLE »). Sans le mot-outil, on fusionnait des lignes de sommaire et deux titres distincts (« FICHE 4 » +
  « EXEMPLE »).
- **Bandeau répété en un seul bloc** alors qu'en marge il est en deux : signature différente → comparer par
  préfixe, et lire le numéro de page **en tête** (« 41 \nTITRE DU RÉFÉRENTIEL … VERSION 2 » donnait p. 2).
- **Corps du texte minoritaire en volume** (tableaux en 7,7 pt plus abondants que le texte en 9,5 pt) : tout le
  texte courant devient un niveau de titre. Option `taille_corps` dans corpus.json ; `taille_section` pour que
  plusieurs tailles ouvrent une section.
- **Notes de bas de page** en 8 pt pour un corps de 9,9 pt : seuil des notes à 0,85 × corps (le filtre des
  fragments de schéma reste à 0,8).

## Lettrine perdue par le filtre commun

Le filtre commun de l'ingestion (`nettoyage.porte_du_sens`) écarte les passages sans mot de 3 lettres. Une
lettrine non recollée par l'extracteur (« C » isolé avant « ommençons… ») disparaît alors : le paragraphe perd
sa première lettre. Tout extracteur doit recoller ses lettrines (bloc d'une seule majuscule suivi d'un bloc qui
commence par une minuscule) — `generique` le fait. Contrôle : chercher en base les passages de type texte qui
commencent par une minuscule en début de page (le contrôle de qualité le signale : « initiale peut-être perdue »).

## Numéros de page (generique v13)

- **Note de bas de page lue comme numéro** : bloc « ____ \n7 \nVoir un exemple en annexe » dans la marge du bas
  (tout un chapitre daté p. 7 au lieu de p. 22). Un nombre suivi de texte n'est un numéro de page que dans un pied
  de page **répété** (« © Éditeur 2017 22/37 »).
- **Numéro en en-tête** (« 42 - TITRE DU CHAPITRE - PARTIE 3 » / « PARTIE 1 - … - 23 ») : non lu, toutes les
  pages prenaient leur rang dans le PDF (décalage de 2). Motifs stricts : nombre en tête suivi d'un tiret, ou en
  fin précédé d'un tiret — « PARTIE 2 » n'est pas la page 2.
- **Page sans numéro imprimé** : prenait son rang dans le PDF. Passe de cohérence : entre deux numéros **lus**
  cohérents (écart = écart de rang), la page prend le numéro attendu ; cela corrige aussi un numéro aberrant
  (chiffre de schéma, ligne d'index). Ne jamais se servir d'un numéro par défaut comme repère.
- Contrôle : `python3 -m corpus_explorer.controle --qualite` signale les numéros qui reculent ; vérifier aussi un
  échantillon contre le numéro imprimé quand un document est numéroté en en-tête.

## Bibliographie et index (generique v14)

Pages de références reconnues à leur contenu, sans réglage par document : majorité de lignes d'index
(« Nom, Prénom 28 ; 104 », « Cas cité : 64 ») ou de bibliographie (« AUTEUR, Prénom, 1989 : titre », URL, ISBN).
Écartées par `generique` (message sur la sortie d'erreur), option `garder_references` pour un document qui en a
besoin. Révélé par la carte : l'index des noms d'un ouvrage formait à lui seul un « sujet » de noms propres
(490 passages).
