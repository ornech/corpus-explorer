"""Vue 3D de tous les passages actifs, placés par le sens : aucun appel au modèle.

    python3 -m corpus_explorer.vue_passages        → <projet>/data/passages-3d.html
    servie par l'API sur /projets/<projet>/carte, d'où elle interroge l'API du même projet

Position : index sémantique (e5-base), recentré par langue (sinon le premier axe sépare le français de
l'anglais), réduit à 50 dimensions (ACP) puis projeté en 3D par t-SNE. La projection est mise en cache à côté de
l'index (data/index-semantique/tsne-<empreinte>.npy) : elle n'est recalculée que si les passages changent.
Couleur : famille de documents (8 au plus). Pendant une recherche, taille = pertinence pour la recherche, lueur =
convergence (autres familles parmi les passages trouvés reliés). Voisins : les 8 passages les plus proches par le sens (vecteurs
complets, pas la carte) dans d'autres documents et au texte différent — simple proximité, ni équivalence ni
contradiction. Ils servent d'arêtes : liens entre passages trouvés, chemin le plus court entre deux passages.

La page contient le texte des passages, y compris d'ouvrages sous droits : fichier local, à ne pas diffuser.
"""
import html
import json
import re

import numpy as np
from collections import Counter

from . import projet
from .db import connexion
from .nettoyage import normaliser
from .semantique import Index

# Familles : déclarées dans corpus.json (champ « famille ») ; l'ordre d'affichage, donc la couleur, vient de
# familles.json (palette validée du pilote) ; une famille absente de familles.json passe après, dans l'ordre du corpus.
COULEURS = ['#3b6fb6', '#c0692b', '#2f8f5b', '#8a4fb0', '#b5452f', '#2a8a96', '#9a7b1c', '#5b636b']
# Mode « univers » (fond noir) : pas du gris, qui vire au blanc sous la lueur ; colonne sombre de la palette de
# référence (validée sur fond sombre), les teintes voisines (rouge/orange, rose/vert d'eau) sur des familles éloignées
COULEURS_SOMBRE = ['#3987e5', '#d95926', '#199e70', '#9085e9', '#e66767', '#008300', '#c98500', '#d55181']
AUTRES = 'Autres documents'


def familles(p: projet.Projet | None = None) -> list[str]:
    """Noms des familles dans l'ordre d'affichage, 8 au plus (au-delà : regroupées dans « Autres documents »)."""
    p = p or projet.courant()
    corpus = p.corpus()
    ordre = json.loads(p.familles.read_text(encoding='utf-8'))['familles'] if p.familles.exists() else []
    noms = list(dict.fromkeys(ordre + [e.get('famille') or AUTRES for e in corpus]))
    noms = [n for n in noms if any((e.get('famille') or AUTRES) == n for e in corpus)]
    return noms if len(noms) <= len(COULEURS) else noms[:len(COULEURS) - 1] + [AUTRES]


def famille(document_id: str, p: projet.Projet | None = None) -> int:
    p = p or projet.courant()
    noms = familles(p)
    nom = next((e.get('famille') or AUTRES for e in p.corpus() if e['id'] == document_id), AUTRES)
    return noms.index(nom) if nom in noms else len(noms) - 1


def projection(cx, index: Index) -> np.ndarray:
    f = index.dossier / f'tsne-{index.empreinte}.npy'
    if f.exists():
        return np.load(f)
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE
    langue = dict(cx.execute("SELECT p.id, d.langue FROM passage p JOIN document d ON d.id = p.document_id"))
    L = np.array([langue[i] for i in index.ids])
    v = index.v.astype(np.float64).copy()
    for lg in set(L):
        v[L == lg] -= v[L == lg].mean(0)
    print(f'[vue] projection t-SNE de {len(v)} passages (1 à 2 minutes)…')
    # Réglages adaptés à la taille du corpus (un petit projet n'a pas 50 dimensions utiles ni 120 voisins)
    n = len(v)
    xyz = TSNE(3, init='pca', random_state=0, perplexity=min(40, max(2, (n - 1) // 3)), n_jobs=-1).fit_transform(
        PCA(min(50, n - 1, v.shape[1]), random_state=0).fit_transform(v))
    xyz = (xyz - xyz.mean(0)) / np.abs(xyz - xyz.mean(0)).max()
    np.save(f, xyz.astype(np.float32))
    return xyz


# Sujets : regroupement des passages par leur seul sens (k-moyennes sur les vecteurs recentrés par langue), sans
# connaître le document ; chaque sujet est nommé par ses mots les plus propres (fréquents dans le sujet, rares
# ailleurs). Sert à vérifier que la carte groupe par sujet et non par fichier : la répartition des familles de
# chaque sujet est affichée.
N_SUJETS_MAX = 36


def n_sujets(n: int) -> int:
    """Nombre de sujets : 36 au plus, environ un pour 20 passages, 2 au moins."""
    return max(2, min(N_SUJETS_MAX, n // 20))
MOTS_VIDES = set("""avec dans pour par sur sous entre vers chez sans plus moins tres tout tous toute toutes cette ces
celle celui ceux leurs leur notre votre elle elles ils nous vous sont etre avoir fait faire peut peuvent doit doivent
afin ainsi alors aussi autre autres comme dont donc lors meme encore deja bien quel quelle quels quelles chaque
certains certaines plusieurs selon ensemble cadre niveau partie mise place permet permettre egalement notamment
etc the and for with that this from are be or of to in on as by an is it its their which can should must not have
has been will may also into such than other these those more within when where what each through used using""".split())


def sujets(cx, index: Index) -> tuple[np.ndarray, list[str]]:
    k = n_sujets(len(index.ids))
    f = index.dossier / f'sujets-{k}-{index.empreinte}.npz'
    if f.exists():
        z = np.load(f, allow_pickle=False)
        return z['etiquettes'], list(z['libelles'])
    from sklearn.cluster import KMeans
    langue = dict(cx.execute("SELECT p.id, d.langue FROM passage p JOIN document d ON d.id = p.document_id"))
    L = np.array([langue[i] for i in index.ids])
    v = index.v.astype(np.float64).copy()
    for lg in set(L):
        v[L == lg] -= v[L == lg].mean(0)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    print(f'[vue] regroupement de {len(v)} passages en {k} sujets…')
    etiquettes = KMeans(k, n_init=4, random_state=0).fit_predict(v)
    textes = dict(cx.execute("SELECT id, texte FROM passage WHERE statut = 'actif'"))
    mots = [Counter(m for m in re.findall(r'[a-z]{4,}', normaliser(textes[i])) if m not in MOTS_VIDES) for i in index.ids]
    par_sujet = [Counter() for _ in range(k)]
    for k, c in zip(etiquettes, mots):
        par_sujet[k].update(set(c))                       # une voix par passage : un mot répété ne domine pas
    total = Counter()
    for c in par_sujet:
        total.update(c)
    libelles = []
    for k, c in enumerate(par_sujet):
        n = int((etiquettes == k).sum())
        score = {m: (x / n) * np.log(1 + len(etiquettes) / total[m]) for m, x in c.items() if x >= 3}
        libelles.append(' · '.join(m for m, _ in sorted(score.items(), key=lambda t: -t[1])[:4]))
    np.savez(f, etiquettes=etiquettes, libelles=np.array(libelles))
    return etiquettes, libelles



K_VOISINS = 8


def voisins(index: Index, documents: np.ndarray, textes: list[str], k: int = K_VOISINS, bloc: int = 2000):
    """Pour chaque passage : ses k plus proches (cosinus, vecteurs complets) dans d'autres documents et au texte
    différent, leurs similarités, et le nombre de copies du même texte dans d'autres documents (les fiches
    documents qui répètent des paragraphes entiers : sans ce filtre, le voisin serait la même phrase, à similarité 1)."""
    v = index.v
    k = min(k, len(v) - 1)
    cle = np.array([re.sub(r'\W+', ' ', normaliser(t)).strip() for t in textes])
    groupe = np.unique(cle, return_inverse=True)[1]
    J, S_, copies = np.zeros((len(v), k), dtype=int), np.zeros((len(v), k), dtype=np.float32), np.zeros(len(v), dtype=int)
    for a in range(0, len(v), bloc):
        b = slice(a, a + bloc)
        meme_texte = groupe[b, None] == groupe[None, :]
        meme_doc = documents[b, None] == documents[None, :]
        copies[b] = (meme_texte & ~meme_doc).sum(1)
        S = v[b] @ v.T
        S[meme_doc | meme_texte] = -1
        haut = np.argpartition(-S, k, axis=1)[:, :k]
        sh = np.take_along_axis(S, haut, 1)
        ordre = np.argsort(-sh, axis=1)
        J[b], S_[b] = np.take_along_axis(haut, ordre, 1), np.take_along_axis(sh, ordre, 1)
    return J, S_, copies


def construire(p: projet.Projet | None = None) -> str:
    p = p or projet.courant()
    cx = connexion(p.db)
    index = Index(cx, p)
    rangs = {r[0]: k for k, r in enumerate(cx.execute('SELECT id FROM document ORDER BY rowid'))}
    lignes = {r['id']: r for r in cx.execute(
        "SELECT p.id, p.document_id, p.page, p.ref_externe, p.section, p.sous_section, p.type, p.texte "
        "FROM passage p WHERE p.statut = 'actif'")}
    P = [lignes[i] for i in index.ids]
    docs = np.array([p['document_id'] for p in P])
    xyz = projection(cx, index)
    J, S, copies = voisins(index, docs, [p['texte'] for p in P])
    etiquettes, libelles = sujets(cx, index)
    documents = sorted(set(docs), key=lambda d: (famille(d, p), rangs.get(d, 0), d))
    num = {d: k for k, d in enumerate(documents)}
    # diffusion « restreint… » dans corpus.json : l'export des passages le rappelle (extraits à ne pas diffuser)
    restreints = {e['id'] for e in p.corpus() if str(e.get('diffusion') or '').startswith('restreint')}
    donnees = dict(
        projet=p.nom,
        familles=[dict(nom=n, clair=c, sombre=cs) for n, c, cs in zip(familles(p), COULEURS, COULEURS_SOMBRE)],
        documents=[dict(id=d, famille=famille(d, p), n=int((docs == d).sum()), restreint=d in restreints) for d in documents],
        k=int(J.shape[1]),
        sujets=[dict(libelle=l, n=int((etiquettes == k).sum())) for k, l in enumerate(libelles)],
        # voisins à plat : passage i → indices ki[i*k … i*k+k-1], similarités ks (×100, entiers)
        ki=J.ravel().tolist(), ks=np.round(S.ravel() * 100).astype(int).tolist(),
        # colonnes compactes : x, y, z, document, type, page/ref, section, texte, copies, id du passage, sujet
        p=[[round(float(x), 4), round(float(y), 4), round(float(z), 4), num[p['document_id']],
            p['type'], p['ref_externe'] or p['page'] or '', ' / '.join(s for s in (p['section'], p['sous_section']) if s),
            p['texte'], int(copies[k]), int(index.ids[k]), int(etiquettes[k])] for k, (p, (x, y, z)) in enumerate(zip(P, xyz))])
    return PAGE.replace('__TITRE__', html.escape(p.titre())).replace('__S__', str(len(libelles))).replace('__N__', f'{len(P):,}'.replace(',', ' ')).replace('__D__', str(len(documents))) \
        .replace('__DONNEES__', json.dumps(donnees, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))


PAGE = """<!doctype html>
<html lang="fr" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>Carte des passages</title>
<style>
:root { --fond:#f7f7f5; --panneau:#ffffff; --texte:#1f2328; --discret:#5b636b; --bord:#d9dcdf; --scene:#fbfbfa;
  --eteint:#c9cdd1; --accent:#1f2328; --chemin:#d4531f; --survol:#eef1f4; --ouvert:#f3f5f8; --marque:#ffe08a;
  --groupeA:#2a78d6; --groupeB:#c98500; --groupeAB:#1f2328; --marqueB:#ffc9a8; }
:root[data-theme="dark"] { --fond:#0b0d12; --panneau:#11141a; --texte:#e6e8ea; --discret:#9aa3ab; --bord:#262b33;
  --scene:#02030a; --eteint:#283040; --accent:#ffffff; --chemin:#ffb347; --survol:#1a1f27; --ouvert:#161b23; --marque:#6b5310;
  --groupeA:#3987e5; --groupeB:#e8a33d; --groupeAB:#f4f4f4; --marqueB:#7a3d12; }
* { box-sizing:border-box; }
body { margin:0; background:var(--fond); color:var(--texte); font:15px/1.45 system-ui, sans-serif;
  display:flex; flex-direction:column; height:100vh; }
nav.site { display:flex; align-items:center; gap:8px; padding:4px 16px; font-size:13px; color:var(--discret);
  border-bottom:1px solid var(--bord); background:var(--panneau); } nav.site b { color:var(--texte); }
nav.site a { color:var(--discret); } nav.site a:hover { color:var(--texte); }
nav.site .onglets { margin-left:auto; display:flex; gap:14px; } nav.site [aria-current] { color:var(--texte); font-weight:600; }
header { padding:8px 16px; border-bottom:1px solid var(--bord); display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center;
  position:relative; z-index:5; }
h1 { font-size:17px; margin:0; } .discret { color:var(--discret); font-size:13px; }
input[type=search], select { font:inherit; font-size:14px; padding:4px 8px; border:1px solid var(--bord); border-radius:6px;
  background:var(--panneau); color:var(--texte); }
input[type=search] { width:260px; }
input[type=range] { width:110px; vertical-align:middle; }
header label { white-space:nowrap; }
button { font:inherit; font-size:13px; padding:3px 10px; border:1px solid var(--bord); border-radius:6px; background:var(--panneau);
  color:var(--texte); cursor:pointer; }
/* Menus déroulants de la barre */
details.menu { position:relative; }
details.menu > summary { list-style:none; cursor:pointer; font-size:13.5px; padding:4px 10px; border:1px solid var(--bord);
  border-radius:6px; background:var(--panneau); user-select:none; white-space:nowrap; }
details.menu > summary::-webkit-details-marker { display:none; }
details.menu > summary::after { content:' ▾'; color:var(--discret); }
details.menu[open] > summary { border-color:var(--discret); }
.pop { position:absolute; top:calc(100% + 6px); left:0; min-width:300px; max-height:70vh; overflow:auto; background:var(--panneau);
  border:1px solid var(--bord); border-radius:8px; padding:10px 12px; box-shadow:0 8px 24px rgba(0,0,0,.35); font-size:13.5px; }
.pop.droite { left:auto; right:0; width:380px; }
.pop label { display:flex; align-items:center; gap:6px; margin:4px 0; }
.pop .reglage { display:grid; grid-template-columns:90px 1fr; align-items:center; gap:6px; margin:6px 0; }
.famille { display:flex; align-items:center; gap:4px; margin:3px 0; }
.famille .n { margin-left:auto; color:var(--discret); font-variant-numeric:tabular-nums; padding-left:10px; }
.docs { margin:0 0 6px 24px; font-size:12.5px; } .docs summary { color:var(--discret); cursor:pointer; }
.docs label { margin:2px 0; }
main { display:grid; grid-template-columns:300px minmax(0,1fr) 420px; flex:1; min-height:0; }
main.sans-explorer { grid-template-columns:0 minmax(0,1fr) 420px; }
main.sans-explorer #explorer { visibility:hidden; }
/* Fil d'Ariane : ce qui est allumé sur la carte, chaque élément retirable ; Précédent du navigateur = état d'avant */
#ariane { flex-basis:100%; display:flex; flex-wrap:wrap; align-items:center; gap:4px 6px; font-size:13px; min-height:26px; }
#ariane .sep { color:var(--discret); }
#ariane .miette { border:0; background:transparent; padding:2px 4px; text-decoration:underline; text-decoration-color:var(--discret); }
#ariane .actuelle { color:var(--discret); padding:2px 4px; }
#ariane .puce { display:inline-flex; align-items:center; gap:4px; padding:1px 2px 1px 10px; border:1px solid var(--bord);
  border-radius:14px; background:var(--panneau); }
#ariane .puce.lentille { border-color:var(--accent); font-weight:600; }
#ariane .puce button { border:0; background:transparent; padding:0 6px; font-size:15px; line-height:1; }
/* Explorer : vue d'ensemble du corpus, toujours complète, à gauche */
#explorer { border-right:1px solid var(--bord); background:var(--panneau); display:flex; flex-direction:column; min-height:0;
  overflow:hidden; }
.explorer-tete { display:flex; align-items:center; gap:8px; padding:8px 10px 8px 14px; border-bottom:1px solid var(--bord); }
.explorer-tete b { font-size:15px; } .explorer-tete button { margin-left:auto; }
.ex-corps { overflow:auto; flex:1; min-height:0; }
.ex-corps[hidden] { display:none; }
#deplier { position:absolute; top:10px; left:10px; z-index:3; display:none; }
main.sans-explorer #deplier { display:block; }
.sujets li.actif { box-shadow:inset 3px 0 0 var(--accent); background:var(--ouvert); }
.sujets li.vide-sel { opacity:.45; }
.sel { font-weight:600; color:var(--texte); }
/* Tableau sujets × familles (calque plein écran) */
.calque { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:20; display:flex; align-items:center; justify-content:center; }
.calque[hidden] { display:none; }
.calque-boite { background:var(--panneau); color:var(--texte); border:1px solid var(--bord); border-radius:10px; width:min(1200px, 96vw);
  max-height:90vh; display:flex; flex-direction:column; box-shadow:0 12px 40px rgba(0,0,0,.5); }
.calque-boite .barre { gap:12px; }
#matrice { overflow:auto; padding:0 16px 16px; }
#matrice table { border-collapse:separate; border-spacing:2px; font-size:12.5px; width:100%; }
#matrice th { position:sticky; top:0; background:var(--panneau); font-weight:600; padding:6px 4px; vertical-align:bottom; z-index:1; }
#matrice th.fam-col { writing-mode:vertical-rl; transform:rotate(180deg); white-space:nowrap; text-align:left; }
#matrice td { text-align:center; padding:4px 2px; border-radius:3px; cursor:pointer; font-variant-numeric:tabular-nums; min-width:44px; }
#matrice td.sujet { text-align:left; cursor:pointer; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:320px; }
#matrice td.total { color:var(--discret); cursor:default; }
#matrice tr:hover td.sujet { text-decoration:underline; }
#scene { position:relative; overflow:hidden; background:var(--scene); min-height:420px; cursor:grab; }
#bulle { position:absolute; pointer-events:none; background:var(--panneau); color:var(--texte); border:1px solid var(--bord);
  border-radius:6px; padding:6px 8px; font-size:13px; max-width:340px; display:none; box-shadow:0 2px 8px rgba(0,0,0,.3); z-index:2; }
aside { border-left:1px solid var(--bord); background:var(--panneau); display:flex; flex-direction:column; min-height:0;
  overflow-x:hidden; overflow-wrap:anywhere; }   /* une longue chaîne sans espace ne doit jamais élargir le panneau */
.entete { padding:10px 14px; border-bottom:1px solid var(--bord); display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.entete b { font-size:15px; } .entete select { font-size:13px; padding:2px 6px; margin-left:auto; }
#defile { overflow:auto; flex:1; min-height:0; }
.vide { padding:14px; }
.pastille { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align:middle; flex:none; }
/* Liste des passages trouvés */
.mesures { padding:4px 14px 6px; font-size:12px; border-bottom:1px solid var(--bord); }
ul#resultats { list-style:none; margin:0; padding:0; }
.item { border-bottom:1px solid var(--bord); }
.ligne { display:block; width:100%; text-align:left; border:0; border-radius:0; background:transparent; padding:8px 14px; font-size:13.5px; }
.ligne:hover, .ligne:focus-visible { background:var(--survol); outline:none; }
.item.courant { background:var(--ouvert); box-shadow:inset 3px 0 0 var(--accent); }
.ligne .cit { font-weight:600; }
.ligne .extrait { color:var(--discret); margin-top:2px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.ligne .chiffres { display:flex; gap:10px; margin-top:3px; font-size:12px; color:var(--discret); font-variant-numeric:tabular-nums; }
.ligne .chiffres b { color:var(--texte); font-weight:600; }
.ligne .chiffres .actif b { text-decoration:underline; text-decoration-color:var(--discret); }
mark { background:var(--marque); color:inherit; border-radius:2px; padding:0 1px; }
mark.b { background:var(--marqueB); }
.recherche { display:flex; align-items:center; gap:6px; }
.recherche .puce { width:9px; height:9px; border-radius:50%; flex:none; }
.recherche select { font-size:13px; padding:3px 4px; }
#ajouterB, #panierBouton { font-size:13px; }
.tag { display:inline-block; font-size:11px; font-weight:600; padding:0 5px; border-radius:4px; margin-left:6px; color:#000; vertical-align:1px; }
.filtres-groupes { display:flex; gap:4px; padding:6px 14px; border-bottom:1px solid var(--bord); flex-wrap:wrap; }
.filtres-groupes button { font-size:12px; padding:1px 8px; border-radius:12px; }
.filtres-groupes button[aria-pressed="true"] { background:var(--texte); color:var(--panneau); border-color:var(--texte); }
.garde { color:#e8b23a; margin-left:4px; }
.panier li { display:flex; gap:8px; align-items:flex-start; padding:8px 14px; border-bottom:1px solid var(--bord); font-size:13px; }
.panier li .corps { flex:1; cursor:pointer; } .panier li button { border:0; font-size:15px; padding:0 4px; }
.barre .outils { display:flex; gap:6px; margin-left:auto; }
#plus { margin:10px 14px 16px; }
#chemin:not(:empty) { margin:10px 14px; border:1px solid var(--bord); border-radius:8px; padding:4px 12px 8px; font-size:13px; }
#chemin h2 { font-size:14px; margin:6px 0 2px; } #chemin ol { padding-left:20px; margin:4px 0; } #chemin li { margin:3px 0; }
a.lien { color:inherit; text-decoration:underline; text-decoration-color:var(--discret); cursor:pointer; }
/* Onglets du panneau : liste, répartition, sujets */
.onglets { display:flex; border-bottom:1px solid var(--bord); }
.onglets button { flex:1; border:0; border-radius:0; background:transparent; padding:8px 4px; font-size:13.5px; color:var(--discret);
  border-bottom:2px solid transparent; }
.onglets button[aria-selected="true"] { color:var(--texte); border-bottom-color:var(--accent); font-weight:600; }
.puce-filtre { display:inline-flex; align-items:center; gap:4px; font-size:12px; margin:6px 14px 0; padding:1px 4px 1px 8px;
  border:1px solid var(--bord); border-radius:12px; }
.puce-filtre button { border:0; padding:0 4px; font-size:14px; background:transparent; }
.repartition { padding:6px 14px 16px; font-size:13px; }
.repartition .fam { margin:12px 0 4px; display:flex; align-items:center; font-weight:600; }
.repartition .fam .n { margin-left:auto; font-variant-numeric:tabular-nums; }
.repartition .doc { display:grid; grid-template-columns:minmax(0, 1fr) 44px 58px; gap:6px; align-items:center; padding:2px 0 2px 16px; font-size:12px;
  cursor:pointer; border-radius:4px; }
.repartition .doc:hover { background:var(--survol); }
.repartition .doc .nom { overflow-wrap:anywhere; line-height:1.25; }
.repartition .doc .n { text-align:right; font-variant-numeric:tabular-nums; color:var(--discret); }
.barre-fond { height:8px; background:var(--survol); border-radius:4px; overflow:hidden; display:flex; }
.barre-fond span { display:block; height:100%; }
.sujets { list-style:none; margin:0; padding:0; }
.sujets li { padding:8px 14px; border-bottom:1px solid var(--bord); cursor:pointer; font-size:13px; }
.sujets li:hover { background:var(--survol); }
.sujets .tete { display:flex; gap:8px; align-items:baseline; }
.sujets .tete b { font-size:13.5px; } .sujets .tete .n { margin-left:auto; color:var(--discret); font-variant-numeric:tabular-nums; white-space:nowrap; }
.sujets .barre-fond { margin:5px 0 3px; height:10px; }
/* Vue détail : remplace la liste, navigation précédent / suivant */
section.vue { display:flex; flex-direction:column; flex:1; min-height:0; }
section.vue[hidden] { display:none; }
#vueDetail { animation:glisse .18s ease-out; }
@keyframes glisse { from { transform:translateX(18px); opacity:0; } to { transform:none; opacity:1; } }
@media (prefers-reduced-motion: reduce) { #vueDetail { animation:none; } }
.barre { display:flex; align-items:center; gap:8px; padding:8px 14px; border-bottom:1px solid var(--bord); }
.barre #position { margin-left:auto; font-variant-numeric:tabular-nums; }
.barre .nav button { font-size:16px; padding:1px 10px; }
#fiche { overflow:auto; flex:1; min-height:0; padding:14px 16px 20px; font-size:13.5px; }
#fiche h2 { font-size:16px; margin:0 0 2px; display:flex; align-items:center; }
#fiche .meta { color:var(--discret); font-size:12.5px; margin:2px 0; }
#fiche .texte { white-space:pre-wrap; font-size:15px; line-height:1.55; margin:12px 0; padding-left:12px; border-left:3px solid var(--bord); }
#fiche .chiffres { display:grid; grid-template-columns:repeat(4, 1fr); gap:6px; margin:10px 0 4px; }
#fiche .chiffres div { border:1px solid var(--bord); border-radius:6px; padding:5px 8px; font-size:11.5px; color:var(--discret); }
#fiche .chiffres b { display:block; font-size:16px; color:var(--texte); font-variant-numeric:tabular-nums; }
#fiche h3 { font-size:12px; font-weight:600; color:var(--discret); margin:16px 0 6px; text-transform:uppercase; letter-spacing:.05em; }
#fiche ul { list-style:none; padding:0; margin:0; } #fiche li { margin:6px 0; }
#fiche .actions { display:flex; gap:6px; margin-top:14px; flex-wrap:wrap; }
.docs { margin:2px 0 0; font-size:12.5px; } .docs summary { color:var(--discret); cursor:pointer; }
@media (max-width:1100px) { main { grid-template-columns:240px minmax(0,1fr) 360px; } }
@media (max-width:760px) { body { height:auto; } main, main.sans-explorer { grid-template-columns:1fr; } #scene { height:62vh; }
  #explorer { max-height:50vh; }
  aside { border-left:0; border-top:1px solid var(--bord); } .pop.droite { width:300px; } }
</style>
</head>
<body>
<nav class="site" aria-label="Pages du projet"><a id="navProjets" href="#">Projets</a><span class="sep">›</span><b>__TITRE__</b>
  <span class="onglets"><span aria-current="page">Carte</span><a id="navEssai" href="#">Essai de pertinence</a><a id="navApi" href="#">API</a></span></nav>
<header>
  <h1>Carte des passages</h1>
  <span class="recherche"><span class="puce" id="puceA" hidden></span>
    <input type="search" id="cherche" placeholder="Chercher un mot ou une expression" aria-label="Recherche A">
    <select id="mode" aria-label="Type de recherche" title="mot exact, ou par le sens (API locale)"><option value="mots">mot exact</option>
      <option value="sens">par le sens</option></select>
    <button type="button" id="ajouterB" title="Comparer avec une seconde recherche">+ comparer</button></span>
  <span class="recherche" id="rechercheB" hidden><span class="puce" id="puceB"></span>
    <input type="search" id="cherche2" placeholder="Seconde recherche, à comparer" aria-label="Recherche B">
    <button type="button" id="retirerB" aria-label="Retirer la seconde recherche">×</button></span>
  <details class="menu"><summary>Familles</summary><div class="pop" id="legende"></div></details>
  <label class="discret">liens <select id="liens" aria-label="Liens à afficher">
    <option value="trouves">entre passages trouvés</option><option value="choisi">autour du passage choisi</option>
    <option value="tous">tous (dense)</option><option value="aucun">aucun</option></select></label>
  <details class="menu"><summary>Affichage</summary><div class="pop">
    <div class="reglage"><span>brouillard</span><input type="range" id="brouillard" min="0" max="100" value="45"></div>
    <div class="reglage"><span>lueur</span><input type="range" id="lueur" min="0" max="100" value="55"></div>
    <div class="reglage"><span>taille</span><input type="range" id="taille" min="2" max="12" value="4"></div>
    <div class="reglage"><span>luminosité</span><input type="range" id="lumiere" min="20" max="250" value="100"></div>
    <label><input type="checkbox" id="univers" checked> fond sombre</label>
    <label><input type="checkbox" id="rotation"> rotation automatique</label>
    <label><input type="checkbox" id="titres"> afficher les titres</label>
    <p class="discret" style="margin:8px 0 4px">Réglages conservés d'une session à l'autre.</p>
    <button type="button" id="reinitialiser">Revenir aux réglages d'origine</button>
  </div></details>
  <button type="button" id="panierBouton" style="margin-left:auto" title="Passages gardés (touche G sur un passage ouvert)">Panier (0)</button>
  <details class="menu"><summary>Aide</summary><div class="pop droite">
    <p style="margin-top:0"><b>__N__ passages, __D__ documents</b>, placés par le sens : deux points proches à l'écran
    parlent de choses proches.</p>
    <p><b>Position</b> : de quoi parle le passage. <b>Couleur</b> : famille de documents. Pendant une recherche :
    <b>taille</b> = pertinence pour la recherche (proximité de sens, ou nombre d'occurrences du mot) ;
    <b>lueur</b> = convergence : nombre d'autres familles de documents parmi les passages trouvés qui lui sont
    reliés par le sens. Sans recherche, taille et lueur sont uniformes.</p>
    <p><b>Souris</b> : glisser pour tourner, molette pour zoomer, clic droit pour déplacer. Clic sur un point : son détail
    à droite. <b>Maj + clic</b> sur un second point : le plus court chemin de sens entre les deux.</p>
    <p><b>Liste et détail</b> : ↑ ↓ (ou ‹ ›) pour passer d'un passage à l'autre, Échap pour revenir à la liste,
    <b>G</b> pour garder le passage ouvert dans le panier (exportable en Markdown, avec citations).</p>
    <p><b>Par le sens</b> : la recherche passe par l'API locale du projet (à lancer :
    <code>python3 -m uvicorn corpus_explorer.api:app --port 8765</code>) et trouve aussi les passages qui n'emploient
    pas le mot. Valider par Entrée. <b>+ comparer</b> : seconde recherche ; bleu = A seule, ambre = B seule, blanc = les deux. La recherche par mot porte sur le texte des passages (pas sur les titres de section), mot entier : « PRA » ne trouve pas « pratiques ».</p>
    <p><b>Navigation</b> : la ligne sous la barre montre ce qui est allumé (recherche, sujet, filtres, passage) ; × retire
    un élément, « Corpus » efface tout. Le bouton <b>Précédent</b> du navigateur revient à l'état d'avant. À gauche,
    <b>Explorer</b> montre toujours tout le corpus (sujets, documents) ; à droite, les passages et leur détail.</p>
    <p><b>Adresse</b> : la recherche, le sujet, les filtres et le passage ouvert sont gardés dans l'adresse de la page —
    un marque-page rouvre la même vue.</p>
    <p class="discret" style="margin-bottom:0">Liens et voisins : 8 passages les plus proches par le sens, dans d'autres
    documents, au texte différent — proximité seulement, ni équivalence ni contradiction. Des passages de langues
    différentes restent en partie groupés entre eux. Le fichier contient le texte des sources : respecter leurs licences.</p>
  </div></details>
  <nav id="ariane" aria-label="Fil d'Ariane : ce qui est allumé sur la carte"></nav>
</header>
<main id="zones">
  <aside id="explorer" aria-label="Explorer le corpus">
    <div class="explorer-tete"><b>Explorer</b>
      <button type="button" id="ouvrirTableau" title="Tableau sujets × familles, en grand">Tableau ⤢</button>
      <button type="button" id="replier" title="Replier l'explorateur" aria-label="Replier l'explorateur" style="margin-left:0">«</button></div>
    <div class="onglets" role="tablist" id="ongletsExplorer">
      <button type="button" role="tab" data-ex="exSujets" aria-selected="true">Sujets</button>
      <button type="button" role="tab" data-ex="exDocuments" aria-selected="false">Documents</button>
    </div>
    <div class="ex-corps" id="exSujets">
      <p class="discret" style="margin:8px 14px 4px">__S__ sujets formés par le seul sens des passages, sans connaître leur
        document. Barre : part de chaque famille. Clic : le sujet s'allume ; la liste reste ici.</p>
      <ul class="sujets" id="sujets"></ul>
    </div>
    <div class="ex-corps" id="exDocuments" hidden>
      <p class="discret" style="margin:8px 14px 0">Passages par famille et par document. Pendant une recherche : nombre
        trouvés / total ; clic sur un document ou une famille : filtre des résultats. Sans recherche : clic sur un document
        pour l'allumer.</p>
      <div class="repartition" id="repartition"></div>
    </div>
  </aside>
  <div id="scene" role="img" aria-label="Carte 3D des passages : proximité à l'écran = proximité de sens"><div id="bulle"></div>
    <button type="button" id="deplier" title="Afficher l'explorateur">Explorer »</button></div>
  <aside aria-label="Passages mis en lumière">
    <section class="vue" id="vueListe">
      <div class="entete"><b id="compte">Passages</b>
        <select id="tri" aria-label="Trier la liste"><option value="liens">tri : les plus reliés</option><option value="familles">tri : reliés au plus de familles</option>
          <option value="occurrences">tri : occurrences du mot</option><option value="document">tri : par document</option></select></div>
      <div class="filtres-groupes" id="groupes" hidden></div>
      <div class="mesures discret" id="mesures" hidden><b>liens</b> : passages trouvés reliés par le sens ·
        <b>fam.</b> : autres familles parmi eux · <b>×</b> : occurrences du mot · <b>n°</b> : identifiant du passage</div>
      <div id="defile">
        <div id="chemin"></div>
        <ul id="resultats"></ul>
        <div id="vide" class="vide discret">Tapez un mot dans la recherche : les passages qui le contiennent s'allument sur la
          carte et s'affichent ici. Un clic sur un point de la carte ouvre aussi son détail.</div>
        <button id="plus" hidden></button>
      </div>
    </section>
    <section class="vue" id="vuePanier" hidden>
      <div class="barre"><button type="button" id="retourPanier">← Liste</button>
        <span class="outils"><button type="button" id="exporter">Exporter (.md)</button><button type="button" id="copier">Copier</button>
        <button type="button" id="vider">Vider</button></span></div>
      <div id="defilePanier" style="overflow:auto;flex:1;min-height:0"><ul class="panier" id="panier" style="list-style:none;margin:0;padding:0"></ul>
        <p id="panierVide" class="vide discret">Panier vide. Ouvrez un passage et cliquez « Garder » (ou touche G) : il est
        conservé ici d'une session à l'autre, prêt à exporter avec sa citation.</p></div>
    </section>
    <section class="vue" id="vueDetail" hidden>
      <div class="barre"><button type="button" id="retour">← Liste</button>
        <span id="position" class="discret"></span>
        <span class="nav"><button type="button" id="prec" aria-label="Passage précédent">‹</button><button type="button" id="suiv" aria-label="Passage suivant">›</button></span></div>
      <div id="fiche"></div>
    </section>
  </aside>
</main>
<div class="calque" id="tableau" hidden role="dialog" aria-modal="true" aria-label="Tableau sujets × familles">
  <div class="calque-boite">
    <div class="barre"><b>Sujets × familles</b>
      <span class="discret" id="tableauSous"></span>
      <button type="button" id="fermerTableau" style="margin-left:auto" aria-label="Fermer">×</button></div>
    <p class="discret" style="margin:8px 16px">Chaque case : nombre de passages du sujet (ligne) dans la famille (colonne) ;
      teinte = part de la ligne. Un sujet dont la teinte se répartit sur plusieurs colonnes est partagé par plusieurs sources ;
      concentrée dans une colonne, il est propre à une famille. Clic sur un sujet : il s'allume ; clic sur une case : sujet
      et famille.</p>
    <div id="matrice"></div>
  </div>
</div>
<script type="importmap">
{ "imports": { "three": "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js",
               "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.180.0/examples/jsm/" } }
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const D = __DONNEES__, K = D.k;
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const norm = t => String(t ?? '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
const P = D.p.map((r, i) => ({ i, x: r[0], y: r[1], z: r[2], doc: D.documents[r[3]], type: r[4], page: r[5],
  section: r[6], texte: r[7], copies: r[8], id: r[9], cle: norm(r[7]), sujet: r[10] }));   // recherche sur le texte du passage seul, pas sur l'intitulé de section
const parId = new Map(P.map(p => [p.id, p]));
const voisinsDe = i => Array.from({ length: K }, (_, m) => [D.ki[i * K + m], D.ks[i * K + m] / 100]);
const citation = p => /^\\d|^[ivxl]+$/.test(p.page) ? `${p.doc.id}, p. ${p.page}` : `${p.doc.id}, ${p.page}`;
const fam = p => D.familles[p.doc.famille];
const docsActifs = new Set(D.documents.map(d => d.id));
let motif = '', avecTitres = false, choisi = null, chemin = [];
const visible = p => docsActifs.has(p.doc.id) && (avecTitres || p.type !== 'titre');
const trouve = p => !motif || dansReq(R[0], p) || dansReq(R[1], p);
const univers = () => document.documentElement.dataset.theme === 'dark';

// ───── Scène, caméra, rendu avec lueur ─────
const scene = $('scene'), bulle = $('bulle');
const rendu = new THREE.WebGLRenderer({ antialias: true });
rendu.setPixelRatio(devicePixelRatio);
scene.appendChild(rendu.domElement);
const monde = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.005, 100);
camera.position.set(0, 0, 2.3);
const controles = new OrbitControls(camera, rendu.domElement);
controles.enableDamping = true; controles.autoRotateSpeed = 0.6;
const composeur = new EffectComposer(rendu);
composeur.addPass(new RenderPass(monde, camera));
const lueur = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.8, 0.5, 0.0);
composeur.addPass(lueur);
composeur.addPass(new OutputPass());
const brume = new THREE.Fog(0x000000, 1, 10);
monde.fog = brume;

const texture = dessin => { const c = document.createElement('canvas'); c.width = c.height = 64; dessin(c.getContext('2d'));
  return new THREE.CanvasTexture(c); };
const disque = texture(g => { const d = g.createRadialGradient(32, 32, 0, 32, 32, 31);
  d.addColorStop(0, 'rgba(255,255,255,1)'); d.addColorStop(0.55, 'rgba(255,255,255,0.95)'); d.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = d; g.fillRect(0, 0, 64, 64); });
const anneau = texture(g => { g.beginPath(); g.arc(32, 32, 26, 0, 2 * Math.PI); g.lineWidth = 6; g.strokeStyle = '#fff'; g.stroke(); });
// Points : taille et lueur propres à chaque point (pertinence, convergence), en pixels constants à l'écran ; le brouillard
// porte la profondeur. Au-delà de 1, la couleur nourrit la lueur (rendu en virgule flottante).
function matiereNuage(base) {
  const m = new THREE.ShaderMaterial({
    uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog, { carte: { value: null }, base: { value: base }, clair: { value: 0 }, lumiere: { value: 1 } }]),
    vertexShader: `
      attribute float taille;
      attribute float eclat;
      uniform float base;
      varying vec3 vCouleur;
      varying float vEclat;
      #include <fog_pars_vertex>
      void main() {
        vCouleur = color; vEclat = eclat;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mvPosition;
        gl_PointSize = base * taille;
        #include <fog_vertex>
      }`,
    fragmentShader: `
      uniform sampler2D carte;
      uniform float clair;
      uniform float lumiere;
      varying vec3 vCouleur;
      varying float vEclat;
      #include <fog_pars_fragment>
      void main() {
        vec4 t = texture2D(carte, gl_PointCoord);
        if (t.a < 0.05) discard;
        float e = vEclat * lumiere;
        vec3 c = clair > 0.5 ? mix(vec3(1.0), vCouleur, clamp(e, 0.3, 1.0)) : vCouleur * e;
        gl_FragColor = vec4(c, t.a);
        #include <fog_fragment>
      }`,
    vertexColors: true, transparent: true, depthWrite: false, fog: true });
  m.uniforms.carte.value = disque;
  return m;
}
const matPoints = matiereNuage(4 * devicePixelRatio), matTrouves = matiereNuage(9 * devicePixelRatio);
const tailleDe = p => taillePoint(p), eclatDe = p => eclatPoint(p);   // taille = pertinence, lueur = convergence (voir ui)
const matLiens = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55, depthWrite: false });
const matChemin = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.95, depthTest: false });
const marque = new THREE.Sprite(new THREE.SpriteMaterial({ map: anneau, sizeAttenuation: false, depthTest: false, transparent: true }));
marque.scale.set(0.035, 0.035, 1); marque.renderOrder = 10; marque.visible = false; monde.add(marque);
// Halo du passage choisi : auréole de la couleur de sa famille, pulsante, captée par la lueur
const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: disque, sizeAttenuation: false, depthTest: false, transparent: true,
  blending: THREE.AdditiveBlending }));
halo.renderOrder = 9; halo.visible = false; monde.add(halo);
function pulser(t) {
  if (!halo.visible) return;
  const k = 1 + 0.25 * Math.sin(t / 380);
  halo.scale.set(0.07 * k, 0.07 * k, 1); halo.material.opacity = univers() ? 0.9 : 0.55;
}
const comete = new THREE.Sprite(new THREE.SpriteMaterial({ map: disque, sizeAttenuation: false, depthTest: false, transparent: true }));
comete.scale.set(0.03, 0.03, 1); comete.renderOrder = 11; comete.visible = false; monde.add(comete);


let nuage = null, trouves = null, liens = null, ligneChemin = null, affiches = [];
const retirer = o => { if (o) { monde.remove(o); o.geometry.dispose(); } return null; };
function nuagePoints(liste, mat, couleur, estompe = () => false) {
  const n = liste.length, pos = new Float32Array(n * 3), col = new Float32Array(n * 3), ta = new Float32Array(n), ec = new Float32Array(n);
  const c = new THREE.Color();
  liste.forEach((p, k) => { pos.set([p.x, p.y, p.z], k * 3); couleur(p, c).toArray(col, k * 3);
    const e = estompe(p); ta[k] = e ? 0.7 : tailleDe(p); ec[k] = e ? 0.6 : eclatDe(p); });
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setAttribute('taille', new THREE.BufferAttribute(ta, 1)); g.setAttribute('eclat', new THREE.BufferAttribute(ec, 1));
  const o = new THREE.Points(g, mat); monde.add(o); return o;
}
function construire() {
  nuage = retirer(nuage); trouves = retirer(trouves);
  const eteint = new THREE.Color(css('--eteint'));
  affiches = P.filter(visible);
  preparerResultats();               // mesures de la recherche, avant de dessiner (taille et lueur en dépendent)
  nuage = nuagePoints(affiches, matPoints, (p, c) => motif && !trouve(p) ? c.copy(eteint) : c.set(couleurPoint(p)),
    p => motif && !trouve(p));
  if (motif) trouves = nuagePoints(affiches.filter(trouve), matTrouves, (p, c) => c.set(couleurPoint(p)));
  construireLiens();
  liste();
}

// ───── Liens (arêtes) ─────
function construireLiens() {
  liens = retirer(liens);
  const mode = $('liens').value, paires = new Map();
  const ajoute = (i, j, s) => { const a = Math.min(i, j), b = Math.max(i, j); if (a !== b) paires.set(a * 100000 + b, s); };
  if (mode === 'trouves' && motif) {
    for (const p of affiches) if (trouve(p)) for (const [j, s] of voisinsDe(p.i)) if (visible(P[j]) && trouve(P[j])) ajoute(p.i, j, s);
  } else if (mode === 'choisi' && choisi) {
    for (const [j, s] of voisinsDe(choisi.i)) if (visible(P[j])) ajoute(choisi.i, j, s);
  } else if (mode === 'tous') {
    for (const p of affiches) for (const [j, s] of voisinsDe(p.i).slice(0, 3)) if (visible(P[j])) ajoute(p.i, j, s);
  }
  if (!paires.size) return;
  const pos = new Float32Array(paires.size * 6), col = new Float32Array(paires.size * 6), c = new THREE.Color();
  let k = 0;
  for (const [cle, s] of paires) {
    const a = P[Math.floor(cle / 100000)], b = P[cle % 100000], f = Math.max(0.25, Math.min(1, (s - 0.80) / 0.15));
    pos.set([a.x, a.y, a.z, b.x, b.y, b.z], k * 6);
    c.set(couleurPoint(a)).multiplyScalar(f).toArray(col, k * 6); c.set(couleurPoint(b)).multiplyScalar(f).toArray(col, k * 6 + 3);
    k++;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  liens = new THREE.LineSegments(g, matLiens); monde.add(liens);
}

// ───── Chemin le plus court (Dijkstra sur le graphe des voisins, poids = 1 − similarité) ─────
const adjacence = (() => { const a = P.map(() => []);
  P.forEach(p => voisinsDe(p.i).forEach(([j, s]) => { a[p.i].push([j, 1 - s]); a[j].push([p.i, 1 - s]); })); return a; })();
function plusCourt(depart, arrivee) {
  const dist = new Float64Array(P.length).fill(Infinity), prec = new Int32Array(P.length).fill(-1), tas = [[0, depart]];
  dist[depart] = 0;
  const pousse = e => { tas.push(e); let k = tas.length - 1;
    while (k > 0) { const m = (k - 1) >> 1; if (tas[m][0] <= tas[k][0]) break; [tas[m], tas[k]] = [tas[k], tas[m]]; k = m; } };
  const tire = () => { const h = tas[0], f = tas.pop();
    if (tas.length) { tas[0] = f; let k = 0; for (;;) { const l = 2 * k + 1, r = l + 1; let m = k;
      if (l < tas.length && tas[l][0] < tas[m][0]) m = l; if (r < tas.length && tas[r][0] < tas[m][0]) m = r;
      if (m === k) break; [tas[m], tas[k]] = [tas[k], tas[m]]; k = m; } } return h; };
  while (tas.length) {
    const [d, u] = tire(); if (u === arrivee) break; if (d > dist[u]) continue;
    for (const [v, w] of adjacence[u]) if (visible(P[v]) && d + w < dist[v]) { dist[v] = d + w; prec[v] = u; pousse([dist[v], v]); }
  }
  if (!isFinite(dist[arrivee])) return [];
  const res = []; for (let u = arrivee; u !== -1; u = prec[u]) res.push(u); return res.reverse();
}
function tracerChemin(depart, arrivee) {
  ligneChemin = retirer(ligneChemin);
  chemin = plusCourt(depart.i, arrivee.i);
  const el = $('chemin');
  if (!chemin.length) { el.innerHTML = '<p class="discret">Aucun chemin entre ces deux passages parmi les documents affichés.</p>'; comete.visible = false; return; }
  const g = new THREE.BufferGeometry().setFromPoints(chemin.map(i => new THREE.Vector3(P[i].x, P[i].y, P[i].z)));
  matChemin.color.set(css('--chemin'));
  ligneChemin = new THREE.Line(g, matChemin); ligneChemin.renderOrder = 9; monde.add(ligneChemin);
  comete.material.color.set(css('--chemin')); comete.visible = true; departComete = performance.now();
  el.innerHTML = `<h2>Chemin de sens : ${chemin.length - 1} pas</h2>
    <p class="discret">Chaque pas relie deux passages voisins par le sens (similarité indiquée). <button id="effacer">effacer</button></p>
    <ol>${chemin.map((i, k) => `<li><span class="pastille" style="background:${fam(P[i]).couleur}"></span><a href="#" data-i="${i}">${esc(citation(P[i]))}</a>
      ${k ? `<span class="discret">(${similarite(chemin[k - 1], i)})</span>` : ''} — ${esc(P[i].texte.slice(0, 110))}${P[i].texte.length > 110 ? '…' : ''}</li>`).join('')}</ol>`;
  el.querySelectorAll('[data-i]').forEach(a => a.onclick = ev => { ev.preventDefault(); afficher(P[+a.dataset.i], true); });
  $('effacer').onclick = () => { ligneChemin = retirer(ligneChemin); chemin = []; comete.visible = false; el.innerHTML = ''; };
}
const similarite = (a, b) => { const v = voisinsDe(a).find(([j]) => j === b) || voisinsDe(b).find(([j]) => j === a); return v ? v[1].toFixed(2) : '—'; };
let departComete = 0;
function bougerComete(t) {
  if (!comete.visible || chemin.length < 2) return;
  const u = (Math.max(0, t - departComete) / (900 * (chemin.length - 1))) % 1, x = u * (chemin.length - 1), k = Math.floor(x), f = x - k;
  const a = P[chemin[k]], b = P[chemin[Math.min(k + 1, chemin.length - 1)]];
  comete.position.set(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, a.z + (b.z - a.z) * f);
}

// ───── Thème, brouillard, lueur ─────
function theme() {
  D.familles.forEach(f => f.couleur = univers() ? f.sombre : f.clair);
  legende();
  const fond = new THREE.Color(css('--scene'));
  monde.background = fond; brume.color = fond;
  const add = univers() ? THREE.AdditiveBlending : THREE.NormalBlending;
  for (const m of [matPoints, matTrouves, matLiens]) { m.blending = add; m.needsUpdate = true; }
  for (const m of [matPoints, matTrouves]) m.uniforms.clair.value = univers() ? 0 : 1;
  marque.material.color.set(css('--accent'));
  matChemin.color.set(css('--chemin')); comete.material.color.set(css('--chemin'));
  construire();
}
function majBrouillard() {
  const k = $('brouillard').value / 100, d = camera.position.distanceTo(controles.target), r = 1.1;
  brume.near = k === 0 ? 1e5 : Math.max(0.01, d - r * (1 - 0.7 * k));
  brume.far = k === 0 ? 2e5 : d + r * (0.3 + 2.2 * (1 - k));
}
const majLueur = () => { lueur.strength = univers() ? $('lueur').value / 100 * 1.6 : 0; };

function taille() {
  const w = scene.clientWidth, h = scene.clientHeight;
  rendu.setSize(w, h); composeur.setSize(w, h); lueur.resolution.set(w, h);
  camera.aspect = w / h; camera.updateProjectionMatrix();
}
addEventListener('resize', taille); taille();

// ───── Vol animé de la caméra ─────
let vol = null;
function volerVers(p) {
  const cible = new THREE.Vector3(p.x, p.y, p.z), dir = camera.position.clone().sub(controles.target);
  vol = { t0: performance.now(), deT: controles.target.clone(), aT: cible, deP: camera.position.clone(),
          aP: cible.clone().add(dir.setLength(Math.min(dir.length(), 0.8))) };
}
function avancerVol(t) {
  if (!vol) return;
  const u = Math.min(1, (t - vol.t0) / 900), e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
  controles.target.lerpVectors(vol.deT, vol.aT, e); camera.position.lerpVectors(vol.deP, vol.aP, e);
  if (u === 1) vol = null;
}
(function boucle(t) {
  avancerVol(t); controles.update(); majBrouillard(); bougerComete(t); pulser(t);
  composeur.render(); requestAnimationFrame(boucle);
})(0);

// ───── Recherches A et B : par mot exact, ou par le sens (API locale) ─────
const R = [{ saisie: '', norm: '', ens: null, scores: null }, { saisie: '', norm: '', ens: null, scores: null }];
// API du projet : servie par l'API, la page l'interroge à sa propre adresse ; ouverte en fichier, l'API locale
const API_DEFAUT = location.protocol.startsWith('http') ? new URL('.', location.href).href.replace(/\\/$/, '')
  : 'http://127.0.0.1:8765/projets/' + D.projet;
const API = new URLSearchParams(location.hash.slice(1)).get('api') || API_DEFAUT;
for (const [id, chemin] of [['navProjets', '/'], ['navEssai', '/projets/' + D.projet + '/essai'], ['navApi', '/docs']])
  document.getElementById(id).href = new URL(chemin, API).href;
let erreurSens = '';
// Mot exact : mot entier (ou expression), pluriel en -s / -x admis ; « pra » ne trouve plus « pratiques »
function motRegex(n) {
  const e = n.split(/\\s+/).map(m => m.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')).join('\\\\s+');
  return new RegExp('(?<![a-z0-9])' + e + '(?:s|x)?(?![a-z0-9])', 'g');
}
const dansReq = (q, p) => !!q.norm && (q.ens ? q.ens.has(p.i) : p.cle.search(q.re) !== -1);
const comparaison = () => !!(R[0].norm && R[1].norm);
const groupe = p => { const a = dansReq(R[0], p), b = dansReq(R[1], p); return a && b ? 'AB' : a ? 'A' : b ? 'B' : ''; };
const CG = {};
const couleursGroupes = () => CG[univers()] ??= { A: css('--groupeA'), B: css('--groupeB'), AB: css('--groupeAB') };
function couleurPoint(p) {
  if (!comparaison()) return fam(p).couleur;
  const g = groupe(p); return g ? couleursGroupes()[g] : fam(p).couleur;
}
const termesMots = () => R.map((q, k) => [q, k ? 'b' : '']).filter(([q]) => q.norm && !q.ens).map(([q, c]) => [q.re, c]);
const modeSens = () => $('mode').value === 'sens';
async function chercherSens(q) {
  const u = `${API}/recherche-sens?q=${encodeURIComponent(q.saisie)}&limite=150&titres=false`;
  const r = await fetch(u);
  if (!r.ok) throw new Error(r.status === 422 ? 'requête trop courte (3 caractères au moins)' : `erreur ${r.status}`);
  const res = await r.json();
  q.ens = new Set(); q.scores = new Map();
  for (const x of res.passages) { const p = parId.get(x.id); if (p) { q.ens.add(p.i); q.scores.set(p.i, x.score); } }
}
async function appliquerRecherches() {
  erreurSens = '';
  for (const [q, champ] of [[R[0], 'cherche'], [R[1], 'cherche2']]) {
    q.saisie = $(champ).value.trim(); q.norm = q.saisie ? norm(q.saisie) : ''; q.ens = null; q.scores = null;
    q.re = q.norm ? motRegex(q.norm) : null; q.sujet = undefined; q.document = undefined;
    if (q.norm && modeSens()) {
      try { await chercherSens(q); }
      catch (e) { erreurSens = e instanceof TypeError
        ? `API locale injoignable (${API}). Lancer : python3 -m uvicorn corpus_explorer.api:app --port 8765`
        : `Recherche par le sens : ${e.message}`; q.norm = ''; }
    }
  }
  motif = R[0].norm || R[1].norm || '';
  filtreDoc = ''; filtreFam = null;
  // Le passage choisi avant cette recherche n'en fait pas partie : on efface son halo, qui passerait pour un résultat
  if (choisi && motif && !trouve(choisi)) { choisi = null; marque.visible = false; halo.visible = false; }
  $('puceA').hidden = $('rechercheB').hidden;
  revenirListe(); construire();
}

// ───── Désignation d'un point : à l'écran, le plus proche du curseur (rayon de capture généreux) ─────
const RAYON_CAPTURE = 14, ecran = new THREE.Vector3();
function pointe(ev) {
  const r = rendu.domElement.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
  const essai = liste => { let best = null, dMin = RAYON_CAPTURE;
    for (const p of liste) {
      ecran.set(p.x, p.y, p.z).project(camera);
      if (ecran.z < -1 || ecran.z > 1) continue;
      const d = Math.hypot((ecran.x + 1) / 2 * r.width - mx, (1 - ecran.y) / 2 * r.height - my);
      if (d < dMin) { dMin = d; best = p; }
    }
    return best; };
  return (motif && essai(affiches.filter(trouve))) || essai(affiches);
}
const apercu = new THREE.Sprite(new THREE.SpriteMaterial({ map: anneau, sizeAttenuation: false, depthTest: false,
  transparent: true, opacity: 0.6 }));
apercu.scale.set(0.028, 0.028, 1); apercu.renderOrder = 12; apercu.visible = false; monde.add(apercu);
let survolPrevu = null;
rendu.domElement.addEventListener('pointermove', ev => {
  if (survolPrevu) return;
  survolPrevu = requestAnimationFrame(() => { survolPrevu = null;
    if (ev.buttons) { bulle.style.display = 'none'; apercu.visible = false; return; }
    const p = pointe(ev);
    rendu.domElement.style.cursor = p ? 'pointer' : 'grab';
    if (!p) { bulle.style.display = 'none'; apercu.visible = false; return; }
    apercu.position.set(p.x, p.y, p.z); apercu.material.color.set(css('--accent')); apercu.visible = true;
    const r = scene.getBoundingClientRect();
    bulle.innerHTML = `<b>${esc(citation(p))}</b><br>${esc(p.texte.slice(0, 160))}${p.texte.length > 160 ? '…' : ''}`;
    bulle.style.left = Math.min(ev.clientX - r.left + 16, r.width - 350) + 'px';
    bulle.style.top = (ev.clientY - r.top + 16) + 'px'; bulle.style.display = 'block';
  });
});
rendu.domElement.addEventListener('pointerleave', () => { bulle.style.display = 'none'; apercu.visible = false; });
let appui = null;
rendu.domElement.addEventListener('pointerdown', ev => appui = [ev.clientX, ev.clientY]);
rendu.domElement.addEventListener('pointerup', ev => {
  if (!appui || Math.hypot(ev.clientX - appui[0], ev.clientY - appui[1]) > 5) return;
  const p = pointe(ev); if (!p) return;
  if (ev.shiftKey && choisi && p !== choisi) tracerChemin(choisi, p); else afficher(p);
});

// ───── Panier : passages gardés, d'une session à l'autre (stockage du navigateur) ─────
const CLE_PANIER = 'carte-passages-panier';
let panier = (() => { try { return JSON.parse(localStorage.getItem(CLE_PANIER) || '[]'); } catch { return []; } })();
const garde = p => panier.includes(p.id);
function ecrirePanier() {
  try { localStorage.setItem(CLE_PANIER, JSON.stringify(panier)); } catch { /* navigation privée : panier de session */ }
  $('panierBouton').textContent = `Panier (${panier.length})`;
}
function basculerGarde(p) {
  panier = garde(p) ? panier.filter(id => id !== p.id) : [...panier, p.id];
  ecrirePanier();
  const b = $('garder'); if (b && choisi === p) b.textContent = garde(p) ? '★ Gardé' : '☆ Garder';
  if (!$('vuePanier').hidden) dessinerPanier();
}
function dessinerPanier() {
  const ps = panier.map(id => parId.get(id)).filter(Boolean);
  $('panierVide').hidden = !!ps.length;
  $('panier').innerHTML = ps.map(p => `<li data-i="${p.i}"><span class="pastille" style="background:${fam(p).couleur};margin-top:5px"></span>
    <div class="corps"><b>${esc(citation(p))}</b><br><span class="discret">${esc(p.texte.slice(0, 150))}${p.texte.length > 150 ? '…' : ''}</span></div>
    <button type="button" data-retirer="${p.id}" aria-label="Retirer du panier" title="Retirer">×</button></li>`).join('');
}
function markdownPanier() {
  const ps = panier.map(id => parId.get(id)).filter(Boolean);
  const date = new Date().toISOString().slice(0, 10);
  return [`# Passages retenus — carte des passages (${date})`, '',
    `${ps.length} passage(s). Textes fidèles aux sources ; citation = identifiant du document dans le projet + page.`, '',
    ...ps.flatMap((p, k) => [`## ${k + 1}. ${citation(p)}`, '',
      `*${fam(p).nom}${p.section ? ' — ' + p.section : ''}*`, '',
      ...p.texte.split('\\n').map(l => '> ' + l), '',
      ...(p.doc.restreint ? ['*Diffusion restreinte : extrait à usage local, ne pas diffuser.*', ''] : [])])].join('\\n');
}
$('panierBouton').onclick = () => { montrerVue('vuePanier'); dessinerPanier(); };
$('retourPanier').onclick = () => montrerVue('vueListe');
$('panier').addEventListener('click', ev => {
  const r = ev.target.closest('[data-retirer]');
  if (r) { panier = panier.filter(id => id !== +r.dataset.retirer); ecrirePanier(); dessinerPanier(); return; }
  const li = ev.target.closest('li'); if (li) { vueRetour = 'vuePanier'; afficher(P[+li.dataset.i], true); }
});
$('exporter').onclick = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([markdownPanier()], { type: 'text/markdown' }));
  a.download = `passages-retenus-${new Date().toISOString().slice(0, 10)}.md`; a.click(); URL.revokeObjectURL(a.href);
};
$('copier').onclick = async () => { try { await navigator.clipboard.writeText(markdownPanier()); $('copier').textContent = 'Copié ✓'; }
  catch { $('copier').textContent = 'Copie refusée'; } setTimeout(() => $('copier').textContent = 'Copier', 1500); };
$('vider').onclick = () => { if (panier.length && confirm(`Retirer les ${panier.length} passages du panier ?`)) { panier = []; ecrirePanier(); dessinerPanier(); } };

// ───── Liste des passages mis en lumière, avec leurs mesures ─────
const PAS = 150;
let resultats = [], montres = PAS, defileListe = 0, filtreGroupe = '', vueRetour = 'vueListe';
function normalise(texte) {
  let n = ''; const pos = [];
  for (let k = 0; k < texte.length; k++)
    for (const ch of texte[k].normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase()) { n += ch; pos.push(k); }
  return [n, pos];
}
function intervalles(texte) {
  const ts = termesMots(); if (!ts.length) return [];
  const [n, pos] = normalise(texte), iv = [];
  for (const [re, c] of ts)
    for (const m of n.matchAll(re)) iv.push([pos[m.index], pos[m.index + m[0].length - 1] + 1, c]);
  return iv.sort((a, b) => a[0] - b[0]);
}
function surligner(texte) {
  let out = '', d = 0;
  for (const [a, b, c] of intervalles(texte)) {
    if (a < d) continue;
    out += esc(texte.slice(d, a)) + `<mark${c ? ` class="${c}"` : ''}>` + esc(texte.slice(a, b)) + '</mark>'; d = b;
  }
  return out + esc(texte.slice(d));
}
function extraitAutour(p) {
  const iv = intervalles(p.texte), a = iv.length ? iv[0][0] : 0;
  const debut = a > 70 ? p.texte.lastIndexOf(' ', a - 60) + 1 : 0;
  return (debut > 0 ? '…' : '') + surligner(p.texte.slice(debut, debut + 240));
}
const compter = (texte, re) => (texte.match(re) || []).length;
function mesurer() {
  const dans = new Set(resultats.map(p => p.i));
  const relies = new Map(resultats.map(p => [p.i, new Set()]));
  for (const p of resultats) for (const [j] of voisinsDe(p.i)) if (dans.has(j)) { relies.get(p.i).add(j); relies.get(j).add(p.i); }
  const cmp = comparaison();
  for (const p of resultats) {
    const r = relies.get(p.i);
    p.liens = r.size;
    p.familles = new Set([...r].map(j => P[j].doc.famille).filter(f => f !== p.doc.famille)).size;
    p.occurrences = termesMots().reduce((s, [t]) => s + compter(p.cle, t), 0);
    p.score = Math.max(R[0].scores?.get(p.i) ?? 0, R[1].scores?.get(p.i) ?? 0);
    p.groupe = cmp ? groupe(p) : '';
    // pont : passage relié à l'autre recherche (A relié à B, ou passage commun aux deux)
    p.ponts = !cmp ? 0 : p.groupe === 'AB' ? r.size : [...r].filter(j => { const g = groupe(P[j]); return g && g !== p.groupe; }).length;
  }
}
const rangDoc = Object.fromEntries(D.documents.map((d, k) => [d.id, k]));
const TRIS = {
  score: (a, b) => b.score - a.score || a.i - b.i,
  liens: (a, b) => b.liens - a.liens || b.familles - a.familles || a.i - b.i,
  familles: (a, b) => b.familles - a.familles || b.liens - a.liens || a.i - b.i,
  ponts: (a, b) => b.ponts - a.ponts || b.liens - a.liens || a.i - b.i,
  occurrences: (a, b) => b.occurrences - a.occurrences || b.liens - a.liens || a.i - b.i,
  document: (a, b) => rangDoc[a.doc.id] - rangDoc[b.doc.id] || a.i - b.i,
};
function optionsTri() {
  const sel = $('tri'), avant = sel.value, sens = R.some(q => q.ens && q.scores), cmp = comparaison();
  const opts = [...(sens ? [['score', 'proximité de sens']] : []), ['liens', 'les plus reliés'],
    ['familles', 'reliés au plus de familles'], ...(cmp ? [['ponts', 'ponts entre A et B']] : []),
    ...(termesMots().length ? [['occurrences', 'occurrences du mot']] : []), ['document', 'par document']];
  const avaitScore = [...sel.options].some(o => o.value === 'score');
  sel.innerHTML = opts.map(([v, t]) => `<option value="${v}">tri : ${t}</option>`).join('');
  // passage à la recherche par le sens : tri par proximité ; sinon le tri choisi est conservé
  sel.value = sens && !avaitScore ? 'score' : opts.some(([v]) => v === avant) ? avant : opts[0][0];
}
// Résultats de la recherche et leurs mesures ; appelé par construire() avant de dessiner les points
let echelle = { min: 0, max: 1, occ: 1 };
function preparerResultats() {
  resultats = motif ? affiches.filter(trouve) : [];
  mesurer();
  const scores = resultats.map(p => p.score).filter(s => s > 0);
  echelle = { min: Math.min(...scores, 1), max: Math.max(...scores, 0), occ: Math.max(1, ...resultats.map(p => p.occurrences)) };
}
// Taille = pertinence pour la recherche (proximité de sens, sinon occurrences du mot), relative aux résultats affichés
function pertinence(p) {
  if (p.score > 0) return echelle.max > echelle.min ? (p.score - echelle.min) / (echelle.max - echelle.min) : 1;
  return Math.log1p(p.occurrences || 0) / Math.log1p(echelle.occ);
}
const taillePoint = p => !motif || !trouve(p) ? 1 : 0.7 + 1.8 * pertinence(p);
// Lueur = convergence : autres familles de documents parmi les passages trouvés reliés (0 à 4 et plus)
const eclatPoint = p => !motif || !trouve(p) ? 0.9 : 0.4 + 1.3 * Math.min(p.familles || 0, 4) / 4;
function liste() {
  optionsTri();
  resultats.sort(TRIS[$('tri').value]);
  montres = PAS; defileListe = 0;
  compteTexte = motif ? '' : null;
  const cmp = comparaison(), n = g => resultats.filter(p => p.groupe === g).length;
  $('groupes').hidden = !cmp;
  if (!cmp) filtreGroupe = '';
  if (cmp) {
    const cg = couleursGroupes(), puce = g => `<span class="tag" style="background:${cg[g]}">${g === 'AB' ? 'A+B' : g}</span>`;
    $('groupes').innerHTML = [['', `tous ${resultats.length}`], ['A', `${puce('A')} seule ${n('A')}`], ['B', `${puce('B')} seule ${n('B')}`],
      ['AB', `${puce('AB')} les deux ${n('AB')}`]].map(([g, t]) => `<button type="button" data-g="${g}" aria-pressed="${filtreGroupe === g}">${t}</button>`).join('');
  }
  $('mesures').hidden = !resultats.length;
  dessinerListe(); majExplorer();
  if (!$('vueDetail').hidden && choisi) afficher(choisi);
  majAdresse();
}
const visibles = () => resultats.filter(p => (!filtreGroupe || p.groupe === filtreGroupe) && (!filtreDoc || p.doc.id === filtreDoc)
  && (filtreFam === null || p.doc.famille === filtreFam));

// ───── Explorer (à gauche) : vue d'ensemble de tout le corpus, qui reste affichée pendant la navigation ─────
let filtreDoc = '', filtreFam = null;
const couleurFamille = k => D.familles[k].couleur;
// Nom court d'un document dans l'Explorer : sans le préfixe commun à sa famille ni l'année (identifiant complet au survol)
const nomCourt = (() => {
  const noms = {};
  D.familles.forEach((_, k) => {
    const ids = D.documents.filter(d => d.famille === k).map(d => d.id.split('-'));
    let n = 0;
    while (ids.length > 1 && ids.every(s => s.length > n + 1 && s[n] === ids[0][n])) n++;
    ids.forEach(s => { noms[s.join('-')] = s.slice(n).join('-').replace(/-[0-9]{4}$/, ''); });
  });
  return id => noms[id] || id;
})();
const vide = () => ({ saisie: '', norm: '', ens: null, scores: null, re: null });
function barreFamilles(compte, total) {
  return `<div class="barre-fond" title="${compte.map((x, k) => x ? `${D.familles[k].nom} : ${x}` : '').filter(Boolean).join(' · ')}">`
    + compte.map((x, k) => x ? `<span style="width:${100 * x / (total || 1)}%;background:${couleurFamille(k)}"></span>` : '').join('') + '</div>';
}
// Comptes par sujet × famille et par document, sur tout ce qui est affiché (corpus), et dans la sélection en cours
function comptes() {
  const nf = D.familles.length;
  const sujet = D.sujets.map(() => ({ total: 0, sel: 0, fam: Array(nf).fill(0), docs: new Map() }));
  const doc = new Map(D.documents.map(d => [d.id, { total: 0, sel: 0 }]));
  const dans = new Set(resultats.map(p => p.i));
  for (const p of affiches) {
    const s = sujet[p.sujet], d = doc.get(p.doc.id);
    s.total++; s.fam[p.doc.famille]++; s.docs.set(p.doc.id, (s.docs.get(p.doc.id) || 0) + 1); d.total++;
    if (motif && dans.has(p.i)) { s.sel++; d.sel++; }
  }
  return { sujet, doc };
}
function majExplorer() {
  const c = comptes();
  // Sujets : toujours la liste complète, triée par taille ; pendant une recherche, nombre de passages trouvés dans chacun
  const ordre = D.sujets.map((_, k) => k).filter(k => c.sujet[k].total).sort((a, b) => c.sujet[b].total - c.sujet[a].total);
  $('sujets').innerHTML = ordre.map(k => {
    const s = c.sujet[k], [premier, n1] = [...s.docs].sort((a, b) => b[1] - a[1])[0];
    const familles = s.fam.filter(Boolean).length, actif = R[0].sujet === k;
    return `<li data-sujet="${k}" class="${actif ? 'actif' : ''}${motif && !actif && !s.sel ? ' vide-sel' : ''}"
      title="Allumer ce sujet sur la carte"><div class="tete"><b>${esc(D.sujets[k].libelle)}</b>
      <span class="n">${motif && !actif ? `<span class="sel">${s.sel}</span> / ` : ''}${s.total}</span></div>${barreFamilles(s.fam, s.total)}
      <div class="discret">${s.docs.size} doc. · ${familles} famille${familles > 1 ? 's' : ''} · ${Math.round(100 * n1 / s.total)} % ${esc(premier)}</div></li>`;
  }).join('');
  // Documents : par famille ; pendant une recherche, trouvés / total
  const max = Math.max(1, ...[...c.doc.values()].map(d => motif ? d.sel : d.total));
  $('repartition').innerHTML = D.familles.map((f, k) => {
    const docs = D.documents.filter(d => d.famille === k && c.doc.get(d.id).total)
      .sort((a, b) => (motif ? c.doc.get(b.id).sel - c.doc.get(a.id).sel : 0) || c.doc.get(b.id).total - c.doc.get(a.id).total);
    if (!docs.length) return '';
    const tot = docs.reduce((s, d) => s + c.doc.get(d.id).total, 0), sel = docs.reduce((s, d) => s + c.doc.get(d.id).sel, 0);
    return `<div class="fam" data-fam="${k}" style="cursor:${motif ? 'pointer' : 'default'}" title="${motif ? 'Filtrer les résultats sur cette famille' : ''}">
        <span class="pastille" style="background:${f.couleur}"></span>${esc(f.nom)}<span class="n">${motif ? `<span class="sel">${sel}</span> / ` : ''}${tot}</span></div>`
      + docs.map(d => { const x = c.doc.get(d.id), v = motif ? x.sel : x.total;
        return `<div class="doc${filtreDoc === d.id || R[0].document === d.id ? ' actif' : ''}" data-doc="${esc(d.id)}"
          title="${esc(d.id)} — ${motif && R[0].document !== d.id ? 'filtrer les résultats sur ce document' : 'allumer ce document'}"><span class="nom">${esc(nomCourt(d.id))}</span>
          <div class="barre-fond"><span style="width:${100 * v / max}%;background:${f.couleur}"></span></div>
          <span class="n">${motif ? `<span class="sel">${x.sel}</span>/` : ''}${x.total}</span></div>`; }).join('');
  }).join('');
  if (!$('tableau').hidden) dessinerTableau(c);
}
function dessinerTableau(c = comptes()) {
  const ordre = D.sujets.map((_, k) => k).filter(k => c.sujet[k].total).sort((a, b) => c.sujet[b].total - c.sujet[a].total);
  const melanges = ordre.filter(k => c.sujet[k].fam.filter(x => x / c.sujet[k].total >= 0.1).length >= 2).length;
  $('tableauSous').textContent = `${ordre.length} sujets · ${melanges} partagés par au moins deux familles (≥ 10 % chacune)`;
  $('matrice').innerHTML = `<table><thead><tr><th style="text-align:left">Sujet</th>${D.familles.map(f =>
      `<th class="fam-col"><span class="pastille" style="background:${f.couleur}"></span>${esc(f.nom)}</th>`).join('')}<th>total</th></tr></thead><tbody>`
    + ordre.map(k => { const s = c.sujet[k];
      return `<tr><td class="sujet" data-sujet="${k}" title="${esc(D.sujets[k].libelle)}">${esc(D.sujets[k].libelle)}</td>${s.fam.map((x, f) => {
        const part = x / s.total, fond = x ? `background:color-mix(in srgb, ${couleurFamille(f)} ${Math.round(15 + 85 * part)}%, transparent)` : '';
        return `<td data-sujet="${k}" data-fam="${f}" style="${fond}" title="${esc(D.familles[f].nom)} : ${x} passages (${Math.round(100 * part)} %)">${x || ''}</td>`;
      }).join('')}<td class="total">${s.total}</td></tr>`; }).join('') + '</tbody></table>';
}

// ───── Changer ce qui est allumé : sujet, document, ou tout effacer ─────
function allumer(lentille) {
  R[0] = lentille; R[1] = vide();
  $('cherche').value = ''; $('cherche2').value = ''; $('rechercheB').hidden = true; $('puceA').hidden = true;
  motif = R[0].norm; filtreDoc = ''; filtreFam = null; filtreGroupe = '';
  if (choisi && motif && !trouve(choisi)) { choisi = null; marque.visible = false; halo.visible = false; }
  montrerVue('vueListe'); construire(); majAdresse();
}
const choisirSujet = k => allumer({ ...vide(), saisie: `Sujet : ${D.sujets[k].libelle}`, norm: '#sujet' + k, sujet: k,
  ens: new Set(P.filter(p => p.sujet === k).map(p => p.i)) });
const choisirDocument = id => allumer({ ...vide(), saisie: `Document : ${id}`, norm: '#doc' + id, document: id,
  ens: new Set(P.filter(p => p.doc.id === id).map(p => p.i)) });
function toutEffacer() { allumer(vide()); }

$('sujets').addEventListener('click', ev => { const li = ev.target.closest('[data-sujet]'); if (li) choisirSujet(+li.dataset.sujet); });
$('repartition').addEventListener('click', ev => {
  const d = ev.target.closest('[data-doc]'), f = ev.target.closest('[data-fam]');
  if (d) {
    if (motif && R[0].document !== d.dataset.doc) { filtreDoc = filtreDoc === d.dataset.doc ? '' : d.dataset.doc; filtrer(); }
    else choisirDocument(d.dataset.doc);
  } else if (f && motif) { filtreFam = filtreFam === +f.dataset.fam ? null : +f.dataset.fam; filtrer(); }
});
function filtrer() { montres = PAS; montrerVue('vueListe'); dessinerListe(); dessinerAriane(); majExplorer(); majAdresse(); }
$('ongletsExplorer').addEventListener('click', ev => {
  const b = ev.target.closest('[data-ex]'); if (!b) return;
  for (const x of $('ongletsExplorer').querySelectorAll('[data-ex]')) { x.setAttribute('aria-selected', x === b); $(x.dataset.ex).hidden = x !== b; }
});
function replierExplorer(replie) {
  $('zones').classList.toggle('sans-explorer', replie);
  try { localStorage.setItem('carte-passages-explorer', replie ? 'replie' : ''); } catch { }
  setTimeout(taille, 0);
}
$('replier').onclick = () => replierExplorer(true);
$('deplier').onclick = () => replierExplorer(false);
try { if (localStorage.getItem('carte-passages-explorer') === 'replie') replierExplorer(true); } catch { }
$('ouvrirTableau').onclick = () => { $('tableau').hidden = false; dessinerTableau(); $('fermerTableau').focus(); };
$('fermerTableau').onclick = () => { $('tableau').hidden = true; };
$('tableau').addEventListener('click', ev => {
  if (ev.target === $('tableau')) { $('tableau').hidden = true; return; }
  const td = ev.target.closest('[data-sujet]'); if (!td) return;
  $('tableau').hidden = true;
  choisirSujet(+td.dataset.sujet);
  if (td.dataset.fam !== undefined) { filtreFam = +td.dataset.fam; filtrer(); }
});

// ───── Fil d'Ariane : ce qui est allumé, chaque élément retirable ─────
function dessinerAriane() {
  const puce = (texte, action, lentille = false) => `<span class="puce${lentille ? ' lentille' : ''}">${esc(texte)}
    <button type="button" data-a="${action}" aria-label="Retirer : ${esc(texte)}" title="Retirer">×</button></span>`;
  const seg = [motif ? '<button type="button" class="miette" data-a="corpus" title="Tout effacer">Corpus</button>'
                     : `<span class="actuelle">Corpus · ${affiches.length} passages</span>`];
  if (motif) {
    const nom = R[0].sujet !== undefined || R[0].document ? R[0].saisie
      : R.filter(q => q.norm).map(q => `« ${q.saisie} »`).join(' / ') + (modeSens() ? ' (par le sens)' : '');
    seg.push(puce(`${nom} — ${resultats.length}`, 'lentille', true));
  }
  if (filtreFam !== null) seg.push(puce(`famille : ${D.familles[filtreFam].nom}`, 'fam'));
  if (filtreDoc) seg.push(puce(`document : ${filtreDoc}`, 'doc'));
  if (filtreGroupe) seg.push(puce(`${filtreGroupe === 'AB' ? 'A et B' : filtreGroupe + ' seule'}`, 'groupe'));
  if (choisi && !$('vueDetail').hidden) seg.push(`<span class="puce"><button type="button" class="miette" data-a="centrer"
    title="Centrer sur la carte" style="padding:0">${esc(citation(choisi))}</button>
    <button type="button" data-a="passage" aria-label="Fermer le passage" title="Revenir à la liste">×</button></span>`);
  $('ariane').innerHTML = seg.join('<span class="sep">›</span>');
}
$('ariane').addEventListener('click', ev => {
  const b = ev.target.closest('[data-a]'); if (!b) return;
  const a = b.dataset.a;
  if (a === 'corpus' || a === 'lentille') toutEffacer();
  else if (a === 'fam') { filtreFam = null; filtrer(); }
  else if (a === 'doc') { filtreDoc = ''; filtrer(); }
  else if (a === 'groupe') { filtreGroupe = ''; liste(); }
  else if (a === 'centrer' && choisi) volerVers(choisi);
  else if (a === 'passage') revenirListe();
});
// En-tête de la liste : passages affichés (après filtres) sur le total de la sélection
let compteTexte = null;
function majCompte(vs) {
  if (compteTexte === null) { $('compte').textContent = 'Passages'; return; }
  const n = vs.length, filtre = n !== resultats.length;
  $('compte').textContent = `${n} passage${n > 1 ? 's' : ''}${filtre ? ` sur ${resultats.length}` : ''}` + compteTexte;
}
function dessinerListe() {
  majCompte(visibles());
  const tri = $('tri').value, actif = k => tri === k ? ' class="actif"' : '', vs = visibles(), cg = couleursGroupes();
  $('resultats').innerHTML = vs.slice(0, montres).map(p => `<li class="item${choisi === p ? ' courant' : ''}" data-i="${p.i}">
    <button class="ligne" type="button"><span class="pastille" style="background:${fam(p).couleur}"></span><span class="cit">${esc(citation(p))}</span>
    ${p.groupe ? `<span class="tag" style="background:${cg[p.groupe]}">${p.groupe === 'AB' ? 'A+B' : p.groupe}</span>` : ''}${garde(p) ? '<span class="garde" title="dans le panier">★</span>' : ''}
    <div class="extrait">${extraitAutour(p)}</div>
    <div class="chiffres"><span title="identifiant du passage dans le projet">n° <b>${p.id}</b></span>
      ${p.score ? `<span${actif('score')} title="proximité de sens avec la requête"><b>${p.score.toFixed(2)}</b> sens</span>` : ''}
      <span${actif('liens')} title="passages trouvés reliés par le sens"><b>${p.liens}</b> liens</span>
      <span${actif('familles')} title="autres familles parmi les passages reliés"><b>${p.familles}</b> fam.</span>
      ${p.groupe ? `<span${actif('ponts')} title="liens vers l'autre recherche"><b>${p.ponts}</b> ponts</span>` : ''}
      ${termesMots().length ? `<span${actif('occurrences')} title="occurrences des mots cherchés"><b>×${p.occurrences}</b></span>` : ''}</div></button></li>`).join('');
  const vide = $('vide');
  vide.hidden = !!vs.length && !erreurSens;
  if (erreurSens) vide.textContent = erreurSens;
  else if (motif && !vs.length) vide.textContent = 'Aucun passage affiché ne correspond à la recherche.';
  else if (!motif) vide.textContent = "Tapez un mot dans la recherche : les passages qui le contiennent s'allument sur la carte et s'affichent ici. Un clic sur un point de la carte ouvre aussi son détail.";
  const reste = vs.length - montres, plus = $('plus');
  plus.hidden = reste <= 0;
  plus.textContent = `Afficher ${Math.min(PAS, reste)} de plus (${reste} restants)`;
}
$('groupes').addEventListener('click', ev => { const b = ev.target.closest('[data-g]'); if (!b) return;
  filtreGroupe = b.dataset.g; montres = PAS;
  $('groupes').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b)); dessinerListe(); });

// ───── Vues du panneau : liste, détail, panier ─────
function montrerVue(id) {
  if (!$('vueListe').hidden) defileListe = $('defile').scrollTop;
  for (const v of ['vueListe', 'vueDetail', 'vuePanier']) $(v).hidden = v !== id;
  if (id === 'vueListe') { dessinerListe(); $('defile').scrollTop = defileListe;
    const item = choisi && $('resultats').querySelector(`[data-i="${choisi.i}"]`); if (item) item.scrollIntoView({ block: 'nearest' }); }
  majAdresse();
}
function groupesVoisins(p) {
  const groupes = new Map();
  for (const [j, s] of voisinsDe(p.i)) {
    const cle = P[j].cle.replace(/[^a-z0-9]+/g, ' ').trim().slice(0, 60);
    if (!groupes.has(cle)) groupes.set(cle, []);
    groupes.get(cle).push([j, s]);
  }
  return [...groupes.values()];
}
function ficheHTML(p) {
  const f = fam(p), dans = resultats.includes(p), cg = couleursGroupes();
  const cases = dans ? [...(p.score ? [[p.score.toFixed(2), 'proximité de sens']] : []), [p.liens, 'liens'], [p.familles, 'autres familles'],
    ...(p.groupe ? [[p.ponts, 'ponts A ↔ B']] : []), ...(termesMots().length ? [['×' + p.occurrences, 'occurrences']] : []),
    [visibles().indexOf(p) + 1 || '—', `rang (${$('tri').selectedOptions[0].text.replace('tri : ', '')})`]] : [];
  return `<h2><span class="pastille" style="background:${f.couleur}"></span>${esc(citation(p))}
      ${p.groupe ? `<span class="tag" style="background:${cg[p.groupe]}">${p.groupe === 'AB' ? 'A+B' : p.groupe}</span>` : ''}</h2>
    <div class="meta">Passage n° <b>${p.id}</b> · ${esc(f.nom)}${p.section ? ' · ' + esc(p.section) : ''}${p.type !== 'texte' ? ' · ' + esc(p.type) : ''}</div>
    <div class="texte" style="border-left-color:${f.couleur}">${surligner(p.texte)}</div>
    ${p.copies ? `<div class="meta">Texte identique dans ${p.copies} autre${p.copies > 1 ? 's' : ''} passage${p.copies > 1 ? 's' : ''} d'autres documents.</div>` : ''}
    ${cases.length ? `<div class="chiffres" style="grid-template-columns:repeat(${Math.min(cases.length, 4)}, 1fr)">${cases.map(([v, t]) => `<div><b>${v}</b>${esc(t)}</div>`).join('')}</div>` : ''}
    <div class="actions"><button type="button" id="garder" title="Touche G">${garde(p) ? '★ Gardé' : '☆ Garder'}</button>
      <button type="button" id="centrer">Centrer sur la carte</button></div>
    <h3>Voisins de sens (autres documents)</h3>
    <ul>${groupesVoisins(p).map(g => { const [j, s] = g[0];
      return `<li><span class="pastille" style="background:${fam(P[j]).couleur}"></span><a class="lien" data-aller="${j}">${esc(citation(P[j]))}</a>
      <span class="discret">${s.toFixed(2)}</span><br><span class="discret">${esc(P[j].texte.slice(0, 120))}${P[j].texte.length > 120 ? '…' : ''}</span>
      ${g.length > 1 ? `<details class="docs"><summary>+ ${g.length - 1} variante${g.length > 2 ? 's' : ''} quasi identique${g.length > 2 ? 's' : ''}</summary>
        ${g.slice(1).map(([k, t]) => `<div><a class="lien" data-aller="${k}">${esc(citation(P[k]))}</a> <span class="discret">${t.toFixed(2)}</span></div>`).join('')}</details>` : ''}</li>`; }).join('')}</ul>
    <p class="discret" style="margin:10px 0 0">Maj + clic sur un autre point de la carte : chemin de sens depuis ce passage.</p>`;
}
function afficher(p, voler = false) {
  choisi = p; marque.position.set(p.x, p.y, p.z); marque.visible = true;
  halo.position.copy(marque.position); halo.material.color.set(couleurPoint(p)); halo.visible = true;
  if ($('vueDetail').hidden && !$('vuePanier').hidden) vueRetour = 'vuePanier';
  else if ($('vueDetail').hidden) vueRetour = 'vueListe';
  montrerVue('vueDetail');
  const vs = visibles(), k = vs.indexOf(p);
  $('position').textContent = k >= 0 ? `${k + 1} / ${vs.length}` : (motif ? 'hors de la recherche' : '');
  $('prec').disabled = k <= 0; $('suiv').disabled = k < 0 || k >= vs.length - 1;
  $('retour').textContent = vueRetour === 'vuePanier' ? `← Panier (${panier.length})` : vs.length ? `← Liste (${vs.length})` : '← Liste';
  const fiche = $('fiche'); fiche.innerHTML = ficheHTML(p); fiche.scrollTop = 0;
  fiche.querySelectorAll('[data-aller]').forEach(a => a.onclick = () => {
    const q = P[+a.dataset.aller];
    if (!visible(q)) { docsActifs.add(q.doc.id); if (q.type === 'titre') { avecTitres = true; $('titres').checked = true; } legende(); construire(); }
    afficher(q, true);
  });
  $('centrer').onclick = () => volerVers(p);
  $('garder').onclick = () => basculerGarde(p);
  if ($('liens').value === 'choisi') construireLiens();
  if (voler) volerVers(p);
  majAdresse();
}
function revenirListe() { if (!$('vueDetail').hidden) montrerVue(vueRetour === 'vuePanier' ? 'vuePanier' : 'vueListe');
  if (!$('vuePanier').hidden) dessinerPanier(); }
function parcourir(pas) {
  const vs = visibles(); if (!vs.length) return;
  let k = vs.indexOf(choisi);
  k = k < 0 ? 0 : Math.max(0, Math.min(vs.length - 1, k + pas));
  if (k >= montres) montres = k + 1;
  afficher(vs[k], true);
}
$('retour').onclick = revenirListe;
$('prec').onclick = () => parcourir(-1);
$('suiv').onclick = () => parcourir(1);
$('resultats').addEventListener('click', ev => {
  const b = ev.target.closest('.ligne'); if (b) { vueRetour = 'vueListe'; afficher(P[+b.closest('.item').dataset.i], true); }
});
$('resultats').addEventListener('mouseover', ev => {
  const it = ev.target.closest('.item'); if (!it) return;
  const q = P[+it.dataset.i]; apercu.position.set(q.x, q.y, q.z); apercu.material.color.set(css('--accent')); apercu.visible = true;
});
$('resultats').addEventListener('mouseleave', () => apercu.visible = false);
$('plus').onclick = () => { montres += PAS; dessinerListe(); };
document.addEventListener('keydown', ev => {
  const t = ev.target, saisie = t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA';
  if (t.tagName === 'SELECT' || (t.tagName === 'INPUT' && t.type !== 'search')) return;
  if (ev.key === 'Escape') { if (!$('tableau').hidden) $('tableau').hidden = true; else revenirListe(); return; }
  if (!saisie && (ev.key === 'g' || ev.key === 'G') && choisi && !$('vueDetail').hidden) { basculerGarde(choisi); return; }
  const pas = { ArrowDown: 1, ArrowUp: -1 }[ev.key] ?? (saisie ? null : { ArrowRight: 1, ArrowLeft: -1 }[ev.key]);
  if (pas && resultats.length) { ev.preventDefault(); parcourir(pas); }
});

// ───── Barre : menu des familles, fermeture des menus ─────
function legende() {
  const el = $('legende'); el.innerHTML = '';
  D.familles.forEach((f, k) => {
    const docs = D.documents.filter(d => d.famille === k);
    if (!docs.length) return;
    const tous = docs.every(d => docsActifs.has(d.id)), n = docs.reduce((s, d) => s + d.n, 0);
    const bloc = document.createElement('div');
    bloc.innerHTML = `<label class="famille"><input type="checkbox" ${tous ? 'checked' : ''}>
      <span class="pastille" style="background:${f.couleur}"></span>${esc(f.nom)}<span class="n">${n}</span></label>
      <details class="docs" style="margin:0 0 6px 24px"><summary>${docs.length} document${docs.length > 1 ? 's' : ''}</summary>${docs.map(d => `<label><input type="checkbox" data-doc="${esc(d.id)}"
        ${docsActifs.has(d.id) ? 'checked' : ''}> ${esc(d.id)} <span class="discret">(${d.n})</span></label>`).join('')}</details>`;
    bloc.querySelector('.famille input').onchange = ev => { docs.forEach(d => ev.target.checked ? docsActifs.add(d.id) : docsActifs.delete(d.id));
      legende(); construire(); };
    bloc.querySelectorAll('[data-doc]').forEach(c => c.onchange = () => {
      c.checked ? docsActifs.add(c.dataset.doc) : docsActifs.delete(c.dataset.doc); construire();
      bloc.querySelector('.famille input').checked = docs.every(d => docsActifs.has(d.id)); });
    el.appendChild(bloc);
  });
}
document.addEventListener('pointerdown', ev => document.querySelectorAll('details.menu[open]').forEach(d => {
  if (!d.contains(ev.target)) d.open = false; }));

// ───── État dans l'adresse, historique de navigation ─────
// Ce qui est allumé (recherche, sujet, document, filtres, passage ouvert) forme l'état de navigation : quand il change,
// une entrée d'historique est créée, et le bouton Précédent du navigateur la restaure. Les réglages (tri, affichage)
// remplacent l'entrée courante sans en créer. Plusieurs changements dans la même action donnent une seule entrée.
let pretAdresse = false, restauration = false, derniereCle = null, ecriturePrevue = false;
function majAdresse() {
  if (!pretAdresse || ecriturePrevue) return;
  ecriturePrevue = true;
  queueMicrotask(() => { ecriturePrevue = false; ecrireAdresse(); });
}
function ecrireAdresse() {
  dessinerAriane();
  const a = new URLSearchParams();
  if (R[0].sujet !== undefined) a.set('sujet', R[0].sujet);
  else if (R[0].document) a.set('document', R[0].document);
  else if (R[0].saisie) a.set('q', R[0].saisie);
  if (R[1].saisie) a.set('q2', R[1].saisie);
  if (modeSens() && (R[0].saisie || R[1].saisie) && R[0].sujet === undefined && !R[0].document) a.set('mode', 'sens');
  if (filtreDoc) a.set('doc', filtreDoc);
  if (filtreFam !== null) a.set('fam', filtreFam);
  if (filtreGroupe) a.set('groupe', filtreGroupe);
  if (choisi && !$('vueDetail').hidden) a.set('p', choisi.id);
  const cle = a.toString();
  if ($('tri').value !== $('tri').options[0]?.value) a.set('tri', $('tri').value);
  const sans = D.documents.filter(d => !docsActifs.has(d.id)).map(d => d.id);
  if (sans.length) a.set('sans', sans.join(','));
  if (avecTitres) a.set('titres', '1');
  if (!univers()) a.set('theme', 'clair');
  if ($('liens').value !== 'trouves') a.set('liens', $('liens').value);
  if (API !== API_DEFAUT) a.set('api', API);
  const url = a.toString() ? '#' + a.toString() : location.pathname + location.search;
  if (!restauration && derniereCle !== null && cle !== derniereCle) history.pushState(null, '', url);
  else history.replaceState(null, '', url);
  derniereCle = cle;
}
// Rétablit l'état décrit par l'adresse (ouverture de la page, ou bouton Précédent / Suivant)
async function restaurer() {
  const a = new URLSearchParams(location.hash.slice(1));
  restauration = true;
  try {
    $('cherche').value = a.get('q') || '';
    $('cherche2').value = a.get('q2') || ''; $('rechercheB').hidden = !a.get('q2');
    $('mode').value = a.get('mode') === 'sens' ? 'sens' : 'mots';
    if (a.get('sujet') && D.sujets[+a.get('sujet')]) choisirSujet(+a.get('sujet'));
    else if (a.get('document') && D.documents.some(d => d.id === a.get('document'))) choisirDocument(a.get('document'));
    else await appliquerRecherches();
    filtreDoc = a.get('doc') || ''; filtreFam = a.has('fam') ? +a.get('fam') : null; filtreGroupe = a.get('groupe') || '';
    if (a.get('tri') && TRIS[a.get('tri')] && [...$('tri').options].some(o => o.value === a.get('tri'))) {
      $('tri').value = a.get('tri'); resultats.sort(TRIS[a.get('tri')]); }
    montres = PAS; dessinerListe(); majExplorer();
    const p = a.get('p') && parId.get(+a.get('p'));
    if (p) afficher(p, true); else revenirListe();
    ecrireAdresse();
    await Promise.resolve();
  } finally { restauration = false; }
}
async function lireAdresse() {
  const a = new URLSearchParams(location.hash.slice(1));
  for (const id of (a.get('sans') || '').split(',').filter(Boolean)) docsActifs.delete(id);
  if (a.get('titres')) { avecTitres = true; $('titres').checked = true; }
  if (a.get('theme') === 'clair') { $('univers').checked = false; document.documentElement.dataset.theme = 'light'; }
  if (a.get('liens')) $('liens').value = a.get('liens');
  legende(); theme(); majLueur();
  pretAdresse = true;
  await restaurer();
}
addEventListener('popstate', () => { restaurer(); });

// ───── Réglages d'affichage conservés d'une session à l'autre (stockage du navigateur) ─────
const CLE_REGLAGES = 'carte-passages-reglages';
const REGLAGES = ['taille', 'lumiere', 'lueur', 'brouillard', 'univers', 'rotation', 'titres', 'liens'];
const valeur = el => el.type === 'checkbox' ? el.checked : el.value;
const ORIGINE = Object.fromEntries(REGLAGES.map(id => [id, valeur($(id))]));
function appliquerReglages(r) {
  for (const id of REGLAGES) if (id in r) { const el = $(id); if (el.type === 'checkbox') el.checked = !!r[id]; else el.value = r[id]; }
  avecTitres = $('titres').checked; controles.autoRotate = $('rotation').checked;
  document.documentElement.dataset.theme = $('univers').checked ? 'dark' : 'light';
  matPoints.uniforms.base.value = $('taille').value * devicePixelRatio;
  matTrouves.uniforms.base.value = $('taille').value * 2.2 * devicePixelRatio;
  for (const m of [matPoints, matTrouves]) m.uniforms.lumiere.value = $('lumiere').value / 100;
}
function ecrireReglages() {
  try { localStorage.setItem(CLE_REGLAGES, JSON.stringify(Object.fromEntries(REGLAGES.map(id => [id, valeur($(id))])))); }
  catch { /* navigation privée : réglages de session */ }
}
try { appliquerReglages(JSON.parse(localStorage.getItem(CLE_REGLAGES) || '{}')); } catch { /* réglages d'origine */ }
for (const id of REGLAGES) $(id).addEventListener(id === 'taille' || id === 'lumiere' || id === 'lueur' || id === 'brouillard' ? 'input' : 'change', ecrireReglages);
$('lumiere').oninput = ev => { for (const m of [matPoints, matTrouves]) m.uniforms.lumiere.value = ev.target.value / 100; };
$('reinitialiser').onclick = () => {
  try { localStorage.removeItem(CLE_REGLAGES); } catch { }
  appliquerReglages(ORIGINE); theme(); majLueur();
};

// ───── Branchements ─────
let attente = null;
const relancer = (delai) => { clearTimeout(attente); attente = setTimeout(appliquerRecherches, delai); };
for (const id of ['cherche', 'cherche2']) {
  $(id).addEventListener('input', () => { if (!modeSens()) relancer(150); else if (!$(id).value.trim()) relancer(0); });
  $(id).addEventListener('keydown', ev => { if (ev.key === 'Enter') relancer(0); });
}
$('mode').onchange = () => { $('cherche').placeholder = modeSens() ? 'Une phrase ou un sujet, puis Entrée' : 'Chercher un mot ou une expression';
  relancer(0); };
$('ajouterB').onclick = () => { $('rechercheB').hidden = false; $('puceA').hidden = false; $('cherche2').focus(); };
$('retirerB').onclick = () => { $('cherche2').value = ''; $('rechercheB').hidden = true; relancer(0); };
$('tri').onchange = () => { resultats.sort(TRIS[$('tri').value]); montres = PAS; dessinerListe(); $('defile').scrollTop = 0; majAdresse(); };
$('titres').addEventListener('change', majAdresse);
$('titres').onchange = ev => { avecTitres = ev.target.checked; construire(); };
$('liens').onchange = () => { construireLiens(); majAdresse(); };
$('taille').oninput = ev => { matPoints.uniforms.base.value = ev.target.value * devicePixelRatio;
  matTrouves.uniforms.base.value = ev.target.value * 2.2 * devicePixelRatio; };
$('lueur').oninput = majLueur;
$('rotation').onchange = ev => controles.autoRotate = ev.target.checked;
$('univers').onchange = ev => { document.documentElement.dataset.theme = ev.target.checked ? 'dark' : 'light'; theme(); majLueur(); };
$('puceA').style.background = 'var(--groupeA)'; $('puceB').style.background = 'var(--groupeB)';
ecrirePanier();
lireAdresse();
window.carte = { P, afficher, tracerChemin, camera, controles, resultats: () => resultats, panier: () => panier };
</script>
</body>
</html>
"""


def main():
    p = projet.courant()
    page = construire(p)
    p.carte.parent.mkdir(parents=True, exist_ok=True)
    p.carte.write_text(page, encoding='utf-8')
    # empreinte de l'index d'où vient la carte : la page des projets dit si la carte est à jour
    empreinte = json.loads((p.index / 'actuel.json').read_text(encoding='utf-8'))['empreinte']
    p.carte.with_suffix('.json').write_text(json.dumps(dict(empreinte=empreinte)), encoding='utf-8')
    print(f'→ {p.carte} ({p.carte.stat().st_size / 1e6:.1f} Mo) ; servie sur /projets/{p.nom}/carte')


if __name__ == '__main__':
    main()
