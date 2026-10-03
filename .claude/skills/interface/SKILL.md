---
name: interface
description: Pages de corpus-explorer (page des projets, carte 3D des passages, essai de pertinence) — conventions, choix validés par l'auteur, pièges de la page de la carte écrite dans une chaîne Python, vérification visuelle avec un navigateur sans interface. À appliquer avant toute modification d'une page ou de la carte.
paths: "corpus_explorer/pages/**, corpus_explorer/vue_passages.py"
user-invocable: false
---

# Interface de corpus-explorer

## Les pages (toutes servies par l'API)

| Adresse | Fichier | Rôle |
|---|---|---|
| `/` | `pages/projets.html` | projets, état (documents, passages, index, carte), actions en tâche de fond et journal, nouveau projet, ajout d'un PDF, modification d'une fiche, réanalyse |
| `/projets/<nom>/carte` | produite par `vue_passages.py` dans `<projet>/data/passages-3d.html` | carte 3D des passages ; `pages/carte-absente.html` tant qu'elle n'est pas construite |
| `/projets/<nom>/essai` | `pages/essai.html` | essai de pertinence : mots et sens côte à côte, jugements enregistrés |
| `/docs` | FastAPI | documentation de l'API |

## Conventions communes

- **Bandeau `nav.site`** identique en haut de chaque page : `Projets › <titre du projet> · Carte · Essai de
  pertinence · API`, page courante en `aria-current`. Une nouvelle page le reprend.
- **Adresses relatives au projet** : une page d'un projet appelle `fetch('recherche?…')`, jamais `'/recherche'`,
  pour interroger le projet de sa propre adresse. La carte calcule `API_DEFAUT` depuis `location` ; ouverte en
  fichier, elle vise `http://127.0.0.1:8765/projets/<nom>` (paramètre `#api=` pour une autre adresse).
- **Gabarits** : `__TITRE__` et `__NOM__` remplacés par l'API (`_page()` dans `api.py`), titre échappé.
- **Thèmes clair et sombre** : couleurs en variables CSS sur `:root`, redéfinies sous `prefers-color-scheme: dark`
  et `[data-theme="dark"]`. États avec une icône **et** un libellé (✓ à jour, ! périmé, ✕ absent, ⟳ en cours),
  jamais la couleur seule.
- **Écritures** (POST, PUT, DELETE) en JSON ou `application/pdf`, jamais en formulaire classique : une page d'un
  autre site ne peut pas les déclencher (voir skill `architecture`).
- **Aucune bibliothèque** dans les pages, sauf Three.js pour la carte (jsDelivr, version figée par l'importmap).
- Messages et libellés en français ; erreurs de l'API affichées telles quelles (`detail`).

## Carte des passages : choix validés par l'auteur (ne pas revenir dessus sans lui demander)

- **Position** = sens (e5-base, recentré par langue, ACP 50, t-SNE 3D ; cache par empreinte de l'index). Deux
  points proches parlent de la même chose ; la distance entre groupes éloignés n'a pas de sens précis.
- **Couleur** = famille de documents (8 au plus, palette validée, ordre de `familles.json`).
- **Pendant une recherche : taille = pertinence, lueur = convergence** (nombre d'autres familles parmi les passages
  trouvés reliés). Taille et lueur réglables, réglages
  gardés dans le navigateur.
- **Fond sombre « univers »**, sans étoiles décoratives, brouillard pour la profondeur, lueur (bloom).
- **Trois zones** : Explorer à gauche (sujets, documents, « Tableau ⤢ » sujets × familles), carte au centre,
  résultats à droite (liste triable avec citation, identifiant du passage, scores ; détail d'un passage avec ses
  voisins de sens). **Fil d'Ariane** (Corpus › sujet › passage) et **historique** du navigateur (état dans
  l'adresse : `#q=`, `mode=sens`, `sujet=`, `doc=`, `p=`, `tri=`…) : on peut toujours revenir en arrière. Ce
  découpage a remplacé une version où le choix d'un sujet bloquait la navigation : ne jamais recréer d'impasse.
- **Recherche par mot exact** = mot entier (« PRA » ne trouve pas « pratiques ») ; **par le sens** via l'API.
- **Voisins** : 8 passages les plus proches dans *d'autres* documents, au texte différent ; simple proximité, ni
  équivalence ni contradiction. Servent d'arêtes (liens entre trouvés, plus court chemin).
- **Peu utilisés** (constat du 2026-10-02) : panier et export, comparaison de deux recherches, plus court chemin.
  Proposition en attente : les ranger dans un menu « avancé » plutôt que les supprimer — demander avant.
- **Pas de « force prescriptive »** (repérage des « doit », « il faut », filtre « règles seulement », tri « règles
  d'abord ») : propre au manuel de crise (corpus de règles), sans objet pour un corpus quelconque ; retirée du
  moteur le 2026-10-03 à la demande de l'auteur (elle reste dans le référentiel). Ne pas la réintroduire ; une
  mesure propre à un genre de corpus irait dans une option de projet, après accord.
- Réglages adaptés à la taille du corpus (`n_sujets`, perplexité, voisins) : un petit projet doit rester lisible.

## Pièges

- **La page de la carte est une chaîne Python** (`PAGE = """…"""` dans `vue_passages.py`, non brute) : tout
  antislash du JavaScript se double (`/\\s+/`, `'\\n'`, `replace(/\\/$/, '')`), sinon Python l'interprète ou
  avertit (`invalid escape sequence`). Les pages de `pages/` sont des fichiers HTML ordinaires : pas de doublement.
- Modifier ces fichiers par l'outil d'édition ou un script Python à chaîne délimitée, pas par un heredoc shell non
  protégé (les accents graves et `$` du JavaScript y sont interprétés).
- `innerHTML` reconstruit : réattacher les écouteurs et garder l'état déplié (`details`) d'un rafraîchissement à
  l'autre (voir `ouverts` dans `projets.html`).
- Toute valeur venue des données passe par `esc()` avant `innerHTML`.

## Vérifier une modification (obligatoire)

1. `"$PY" -m pytest -q tests` (les tests vérifient pages, liens et gabarits remplis).
2. Syntaxe du JavaScript d'une page :
   `python3 -c "import re;s=open('corpus_explorer/pages/projets.html').read();open('/tmp/p.js','w').write(re.findall(r'<script>(.*?)</script>',s,re.S)[0])" && node --check /tmp/p.js`
   (pour la carte : générer la page, extraire le `<script type="module">`, `node --check --input-type=module`).
3. **La voir** : lancer une API de démonstration sur un autre port, avec un projet de test hors du dépôt, puis
   capturer la page et relever les erreurs JavaScript :
   ```bash
   CORPUS_PROJETS=/tmp/demo-projets "$PY" -m uvicorn corpus_explorer.api:app --port 8766 &
   python3 ${CLAUDE_SKILL_DIR}/scripts/capturer.py http://localhost:8766/ /tmp/accueil.png
   ```
   Pour un parcours (cliquer, remplir, envoyer), écrire un court script Playwright sur le modèle de
   `scripts/capturer.py` ; accepter les `confirm()` par `page.on('dialog', …)`.
4. Regarder l'image (outil de lecture d'images) : chevauchements, débordements, libellés, états.
5. Arrêter le serveur de démonstration par son port (`fuser -k 8766/tcp`), jamais par `pkill -f` sur une ligne de
   commande qui contient le motif (le shell qui lance la commande se tue lui-même).
