"""API locale de corpus-explorer : tous les projets de projets/, chacun sous /projets/<nom>/…
Seul point d'accès aux bases des projets.

Lancement :  python3 -m uvicorn corpus_explorer.api:app --port 8765
Pages : http://localhost:8765/ (projets et administration), /projets/<nom>/carte, /projets/<nom>/essai ;
documentation interactive : /docs
"""
import json
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from . import etat, profil, projet, sources, taches
from .db import connexion, initialiser
from .nettoyage import normaliser
from .projet import Projet

PAGES = Path(__file__).parent / 'pages'

app = FastAPI(title='corpus-explorer', version='0.2.0')
# Lecture seule depuis une page locale (carte des passages ouverte en fichier : origine « null ») ou localhost.
# Les écritures (POST) n'acceptent que du JSON : une page d'un autre site ne peut pas les déclencher.
app.add_middleware(CORSMiddleware, allow_origins=['null'], allow_origin_regex=r'http://(localhost|127\.0\.0\.1)(:\d+)?',
                   allow_methods=['GET'], allow_headers=[])


def projet_de(nom: str) -> Projet:
    try:
        return projet.ouvrir(nom)
    except LookupError as e:
        raise HTTPException(404, str(e))


# Routes d'un projet : /projets/<nom>/…
pr = APIRouter(prefix='/projets/{nom}')
_inities: set[str] = set()


@contextmanager
def base(p: Projet):
    cx = connexion(p.db)
    try:
        if str(p.db) not in _inities:                        # schéma vérifié une fois par projet et par processus
            initialiser(cx)
            _inities.add(str(p.db))
        yield cx
    finally:
        cx.close()


# ───────────── Modèles de réponse ─────────────
class Document(BaseModel):
    id: str
    titre: str
    editeur: str
    annee: int | None
    version: str | None
    langue: str
    url: str | None
    licence: str | None
    diffusion: str | None
    extracteur: str
    ingere_le: str
    nb_passages: int
    rang: int | None         # ordre dans corpus.json (fixe la couleur d'un document dans les vues)


class Passage(BaseModel):
    id: int
    document_id: str
    ordre: int
    page: str | None
    section: str | None
    sous_section: str | None
    volet: str | None
    ref_externe: str | None
    type: str
    langue: str
    texte: str
    statut: str              # actif | retire
    citation: str            # référence prête à citer : « DOCUMENT-ID, p. 38 »


class CompteDocument(BaseModel):
    document_id: str
    titre: str
    n: int                   # passages trouvés dans ce document
    nb_passages: int         # passages actifs du document (pour situer les positions)
    ordres: list[int]        # position (ordre de lecture) de chaque passage trouvé


class ResultatRecherche(BaseModel):
    requete: str
    total: int
    par_document: list[CompteDocument]     # tous les passages trouvés, pas seulement ceux renvoyés
    passages: list[Passage]


class Contexte(BaseModel):
    passage: Passage
    avant: list[Passage]     # passages précédents du même document, dans l'ordre de lecture
    apres: list[Passage]


class PassageTrouve(Passage):
    score: float             # α × sens + (1 − α) × lexical
    score_sens: float        # cosinus des embeddings (e5-base)
    score_lexical: float     # termes partagés, synonymes du projet compris


class ResultatSens(BaseModel):
    requete: str
    representation: str
    alpha: float
    passages: list[PassageTrouve]


class TermeAssocie(BaseModel):
    terme: str               # forme présente dans la requête
    canonique: str
    nature: str              # synonyme
    associes: list[str]      # autres formes à essayer (synonymes.yaml du projet)


class Evaluation(BaseModel):
    requete: str = Field(min_length=1, max_length=300)
    mode: Literal['plein-texte', 'sens', 'fusion']
    passage_id: int
    rang: int = Field(ge=1)
    jugement: Literal['pertinent', 'partiel', 'hors-sujet']


class BilanMode(BaseModel):
    mode: str
    requetes: int
    jugements: int
    precision: float         # pertinent = 1, partiel = 0,5, hors sujet = 0
    precision_5: float       # même mesure sur les 5 premiers résultats


# ───────────── Outils ─────────────
def _citation(r) -> str:
    ref = r['ref_externe'] or (f"p. {r['page']}" if r['page'] else '')
    return f"{r['document_id']}, {ref}".rstrip(', ')


def _rangs(p: Projet) -> dict[str, int]:
    corpus = p.corpus()
    return {e['id']: k for k, e in enumerate(corpus, 1)}


def _passage(r) -> Passage:
    return Passage(**dict(r), citation=_citation(r))


def _requete_fts(q: str) -> str:
    """Transforme la saisie en requête FTS5 sûre : chaque mot entre guillemets, combinés en ET.
    Les trigrammes imposent au moins 3 caractères par terme ; « isol » trouve isoler, isolement, isolé."""
    termes = [t for t in re.findall(r'"[^"]+"|\S+', normaliser(q)) if len(t.strip('"')) >= 3]
    if not termes:
        raise HTTPException(422, 'Chaque terme doit comporter au moins 3 caractères.')
    return ' AND '.join('"' + t.strip('"').replace('"', '') + '"' for t in termes)


# ───────────── Points d'entrée d'un projet ─────────────
@pr.get('/sante')
def sante(p: Projet = Depends(projet_de)):
    with base(p) as cx:
        n = cx.execute("SELECT count(*) FROM passage WHERE statut = 'actif'").fetchone()[0]
    return {'etat': 'ok', 'passages': n}


@pr.get('/documents', response_model=list[Document])
def documents(p: Projet = Depends(projet_de)):
    with base(p) as cx:
        rows = cx.execute('''SELECT d.*, count(p.id) AS nb_passages
                               FROM document d LEFT JOIN passage p ON p.document_id = d.id AND p.statut = 'actif'
                              GROUP BY d.id ORDER BY d.id''').fetchall()
    rangs = _rangs(p)
    return [Document(**{k: r[k] for k in Document.model_fields if k != 'rang'}, rang=rangs.get(r['id'])) for r in rows]


@app.get('/documents/{doc_id}', response_model=Document)
def document(doc_id: str, p: Projet = Depends(projet_de)):
    with base(p) as cx:
        r = cx.execute('''SELECT d.*, count(p.id) AS nb_passages
                            FROM document d LEFT JOIN passage p ON p.document_id = d.id AND p.statut = 'actif'
                           WHERE d.id = ? GROUP BY d.id''', (doc_id,)).fetchone()
    if not r:
        raise HTTPException(404, f'Document inconnu : {doc_id}')
    return Document(**{k: r[k] for k in Document.model_fields if k != 'rang'}, rang=_rangs(p).get(r['id']))


@pr.get('/passages/{passage_id}', response_model=Passage)
def passage(passage_id: int, p: Projet = Depends(projet_de)):
    with base(p) as cx:
        r = cx.execute('SELECT * FROM passage WHERE id = ?', (passage_id,)).fetchone()
    if not r:
        raise HTTPException(404, f'Passage inconnu : {passage_id}')
    return _passage(r)


@pr.get('/passages/{passage_id}/contexte', response_model=Contexte)
def contexte(passage_id: int, p: Projet = Depends(projet_de), avant: int = Query(2, ge=0, le=20), apres: int = Query(5, ge=0, le=30)):
    """Le passage et ses voisins actifs dans le document (pour juger un titre ou une phrase isolée)."""
    with base(p) as cx:
        r = cx.execute('SELECT * FROM passage WHERE id = ?', (passage_id,)).fetchone()
        if not r:
            raise HTTPException(404, f'Passage inconnu : {passage_id}')
        voisins = lambda signe, n: cx.execute(
            f"""SELECT * FROM passage WHERE document_id = ? AND statut = 'actif' AND ordre {signe} ?
                ORDER BY ordre {'DESC' if signe == '<' else 'ASC'} LIMIT ?""", (r['document_id'], r['ordre'], n)).fetchall()
        av, ap = voisins('<', avant)[::-1], voisins('>', apres)
    return Contexte(passage=_passage(r), avant=[_passage(x) for x in av], apres=[_passage(x) for x in ap])


def _filtres(prefixe: str, document, documents, types, langue, volet, titres, min_car) -> tuple[list[str], list]:
    """Filtres communs aux deux recherches, sur les passages actifs."""
    f, params = [f"{prefixe}statut = 'actif'"], []
    docs = ([document] if document else []) + [d for d in (documents or []) if d]
    if docs:
        f.append(f"{prefixe}document_id IN ({','.join('?' * len(docs))})"); params += docs
    if types:
        f.append(f"{prefixe}type IN ({','.join('?' * len(types))})"); params += types
    for champ, val in (('langue', langue), ('volet', volet)):
        if val:
            f.append(f'{prefixe}{champ} = ?'); params.append(val)
    if not titres:
        f.append(f"{prefixe}type <> 'titre'")
    if min_car:
        f.append(f'length({prefixe}texte) >= ?'); params.append(min_car)
    return f, params


@pr.get('/recherche', response_model=ResultatRecherche)
def recherche(q: str = Query(..., description='Mots recherchés ; "expression exacte" entre guillemets'),
              document: str | None = None,
              documents: list[str] | None = Query(None, description='plusieurs documents (paramètre répété)'),
              volet: str | None = None,
              type: str | None = Query(None, description='texte, liste, ligne-tableau, temoignage…'),
              types: list[str] | None = Query(None, description='plusieurs types (paramètre répété)'),
              langue: str | None = None,
              titres: bool = Query(True, description='false : exclure les titres des résultats'),
              min_car: int = Query(0, ge=0, le=500, description='longueur minimale du passage (écarte intertitres et sommaires)'),
              limite: int = Query(20, ge=1, le=200), p: Projet = Depends(projet_de)):
    fts = _requete_fts(q)
    f, params = _filtres('p.', document, documents, ([type] if type else []) + (types or []), langue, volet,
                         titres, min_car)
    where = ' AND '.join(['passage_fts MATCH ?'] + f)
    params = [fts] + params
    with base(p) as cx:
        total = cx.execute(f'SELECT count(*) FROM passage_fts JOIN passage p ON p.id = passage_fts.rowid WHERE {where}',
                           params).fetchone()[0]
        rows = cx.execute(f'''SELECT p.* FROM passage_fts JOIN passage p ON p.id = passage_fts.rowid
                               WHERE {where} ORDER BY rank LIMIT ?''', params + [limite]).fetchall()
        positions = defaultdict(list)
        for r in cx.execute(f'SELECT p.document_id, p.ordre FROM passage_fts JOIN passage p ON p.id = passage_fts.rowid '
                            f'WHERE {where} ORDER BY p.ordre', params):
            positions[r['document_id']].append(r['ordre'])
        infos = {r['id']: r for r in cx.execute('''SELECT d.id, d.titre, count(p.id) AS nb FROM document d
                                                    JOIN passage p ON p.document_id = d.id AND p.statut = 'actif'
                                                   GROUP BY d.id''')}
    comptes = sorted(positions.items(), key=lambda x: (-len(x[1]), x[0]))
    return ResultatRecherche(requete=fts, total=total, passages=[_passage(r) for r in rows],
                             par_document=[CompteDocument(document_id=d, titre=infos[d]['titre'], n=len(o),
                                                          nb_passages=infos[d]['nb'], ordres=o) for d, o in comptes])


# ───────────── Recherche par le sens et essai de pertinence ─────────────
_index: dict[str, object] = {}                              # un index chargé par projet


def _index_semantique(cx, p: Projet):
    """Index chargé une fois par projet ; 503 explicite s'il manque ou ne correspond plus aux passages."""
    from . import semantique
    i = _index.get(p.nom)
    if i is None or i.empreinte != semantique._empreinte(semantique._passages(cx)):
        try:
            i = _index[p.nom] = semantique.Index(cx, p)
        except FileNotFoundError:
            raise HTTPException(503, 'Index de sens absent : le construire depuis la page des projets '
                                     '(ou python3 -m corpus_explorer.semantique).')
        except LookupError:
            raise HTTPException(503, 'Index de sens périmé (passages modifiés) : le reconstruire depuis la page '
                                     'des projets (ou python3 -m corpus_explorer.semantique).')
    return i


def _trouves(cx, trouves) -> list[PassageTrouve]:
    lignes = {r['id']: r for r in cx.execute('SELECT * FROM passage WHERE id IN (%s)' % ','.join('?' * len(trouves)),
                                             [t[0] for t in trouves])} if trouves else {}
    return [PassageTrouve(**dict(lignes[i]), citation=_citation(lignes[i]), score=round(sc, 4),
                          score_sens=round(se, 4), score_lexical=round(le, 4)) for i, sc, se, le in trouves]


def _representation(alpha: float) -> str:
    from .sens import OPTIONS, REGLAGE
    return f"{OPTIONS[REGLAGE['option']]['modele'].split('/')[-1]} + lexical (α = {alpha:g})"


@pr.get('/recherche-sens', response_model=ResultatSens)
def recherche_sens(q: str = Query(..., min_length=3, description='Phrase ou sujet, en français ou en anglais'),
                   document: str | None = None,
                   documents: list[str] | None = Query(None, description='plusieurs documents (paramètre répété)'),
                   types: list[str] | None = Query(None, description='plusieurs types (paramètre répété)'),
                   langue: str | None = None,
                   titres: bool = Query(True, description='false : exclure les titres des résultats'),
                   min_car: int = Query(0, ge=0, le=500, description='longueur minimale du passage'),
                   alpha: float | None = Query(None, ge=0, le=1, description='part du sens (1 = sens seul, 0 = mots seuls)'),
                   limite: int = Query(10, ge=1, le=200), p: Projet = Depends(projet_de)):
    """Passages les plus proches par le sens (e5-base + score lexical), même sans mot commun."""
    from .sens import REGLAGE
    a = REGLAGE['alpha'] if alpha is None else alpha
    with base(p) as cx:
        index = _index_semantique(cx, p)
        f, params = _filtres('', document, documents, types, langue, None, titres, min_car)
        textes = {r['id']: r['texte'] for r in cx.execute(f"SELECT id, texte FROM passage WHERE {' AND '.join(f)}", params)}
        trouves = index.chercher(q, textes, list(textes), limite, alpha=a)
        passages = _trouves(cx, trouves)
    return ResultatSens(requete=q, representation=_representation(a), alpha=a, passages=passages)


@pr.get('/passages/{passage_id}/semblables', response_model=ResultatSens)
def semblables(passage_id: int,
               documents: list[str] | None = Query(None, description='limiter à ces documents'),
               titres: bool = False, min_car: int = Query(60, ge=0, le=500),
               alpha: float | None = Query(None, ge=0, le=1), limite: int = Query(10, ge=1, le=50),
               p: Projet = Depends(projet_de)):
    """Passages les plus proches d'un passage donné, dans tous les documents (texte identique exclu)."""
    from .sens import REGLAGE
    a = REGLAGE['alpha'] if alpha is None else alpha
    with base(p) as cx:
        r = cx.execute('SELECT * FROM passage WHERE id = ?', (passage_id,)).fetchone()
        if not r:
            raise HTTPException(404, f'Passage inconnu : {passage_id}')
        index = _index_semantique(cx, p)
        if passage_id not in index.position:
            raise HTTPException(422, 'Passage retiré : absent de l\'index sémantique.')
        f, params = _filtres('', None, documents, None, None, None, titres, min_car)
        textes = {x['id']: x['texte'] for x in cx.execute(f"SELECT id, texte FROM passage WHERE {' AND '.join(f)}", params)}
        exclus = {passage_id} | {i for i, t in textes.items() if normaliser(t) == normaliser(r['texte'])}
        trouves = index.chercher(r['texte'], textes, list(textes), limite, alpha=a,
                                 vecteur=index.vecteur(passage_id), exclus=exclus)
        passages = _trouves(cx, trouves)
    return ResultatSens(requete=f"semblables à {_citation(r)}", representation=_representation(a), alpha=a,
                        passages=passages)


@pr.get('/termes-associes', response_model=list[TermeAssocie])
def termes_associes(q: str = Query(..., min_length=3), p: Projet = Depends(projet_de)):
    """Formes équivalentes (synonymes.yaml du projet) des termes présents dans la requête."""
    import yaml
    sy = yaml.safe_load(p.synonymes.read_text(encoding='utf-8')) if p.synonymes.exists() else {}
    texte = f' {normaliser(q)} '
    out = []
    for canon, formes in (sy or {}).items():
        formes = [str(canon)] + [str(x) for x in (formes or [])]
        presentes = [x for x in formes if re.search(r'\b' + re.escape(normaliser(x)) + r'\b', texte)]
        if presentes:
            out.append(TermeAssocie(terme=presentes[0], canonique=str(canon), nature='synonyme',
                                    associes=[x for x in formes if x not in presentes]))
    return out


@pr.post('/evaluations', status_code=201)
def evaluer(e: Evaluation, p: Projet = Depends(projet_de)):
    """Enregistre un jugement de pertinence (le dernier jugement d'un même résultat l'emporte)."""
    with base(p) as cx:
        if not cx.execute('SELECT 1 FROM passage WHERE id = ?', (e.passage_id,)).fetchone():
            raise HTTPException(404, f'Passage inconnu : {e.passage_id}')
    p.evaluations.parent.mkdir(parents=True, exist_ok=True)
    with p.evaluations.open('a', encoding='utf-8') as f:
        f.write(json.dumps(dict(e.model_dump(), le=datetime.now().isoformat(timespec='seconds')), ensure_ascii=False) + '\n')
    return {'enregistre': True}


@pr.get('/evaluations/bilan', response_model=list[BilanMode])
def bilan(p: Projet = Depends(projet_de)):
    """Précision par mode de recherche, sur les jugements saisis dans /essai."""
    valeur = {'pertinent': 1.0, 'partiel': 0.5, 'hors-sujet': 0.0}
    derniers = {}
    if p.evaluations.exists():
        for l in p.evaluations.read_text(encoding='utf-8').splitlines():
            if l.strip():
                j = json.loads(l)
                derniers[(normaliser(j['requete']).strip(), j['mode'], j['passage_id'])] = j
    par_mode = defaultdict(list)
    for (q, mode, _), j in derniers.items():
        par_mode[mode].append((q, j['rang'], valeur[j['jugement']]))
    out = []
    for mode, js in sorted(par_mode.items()):
        haut = [v for _, r, v in js if r <= 5]
        out.append(BilanMode(mode=mode, requetes=len({q for q, _, _ in js}), jugements=len(js),
                             precision=round(sum(v for *_, v in js) / len(js), 3),
                             precision_5=round(sum(haut) / len(haut), 3) if haut else 0.0))
    return out


# ───────────── Administration : état et tâches ─────────────
class NouveauProjet(BaseModel):
    nom: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$', description='nom du dossier : minuscules, chiffres, tirets')
    titre: str = Field(min_length=1, max_length=120)
    langue: str = Field('fr', pattern=r'^[a-z]{2,3}(-[A-Z]{2})?$', description='langue principale (BCP-47)')


class Lancement(BaseModel):
    action: Literal['ingestion', 'controle', 'semantique', 'carte', 'tout', 'ajout']
    documents: list[str] = Field([], description='limiter ingestion et contrôle à ces documents')


class NouveauDocument(BaseModel):
    """Entrée de corpus.json ; champs inconnus : null (ne rien inventer)."""
    id: str = Field(pattern=r'^[A-Z0-9][A-Z0-9-]{1,63}$', description='EDITEUR-SUJET-ANNEE, majuscules et tirets')
    titre: str = Field(min_length=1, max_length=300)
    editeur: str = Field(min_length=1, max_length=200, description='éditeur ou auteur, ou « inconnu »')
    annee: int | None = Field(None, ge=1000, le=2100)
    version: str | None = Field(None, max_length=60)
    langue: str = Field(pattern=r'^[a-z]{2,3}(-[A-Z]{2})?$')
    url: str | None = Field(None, max_length=500)
    fichier: str = Field(pattern=r'^sources/[a-z0-9][a-z0-9._-]{0,120}\.pdf$')
    licence: str = Field(min_length=1, max_length=300, description='licence lue dans le document, ou « inconnue »')
    diffusion: Literal['public', 'restreint']
    famille: str | None = Field(None, max_length=60)
    extracteur: str = Field(pattern=r'^[a-z0-9_]+$')
    options: dict = {}


@pr.post('/sources', status_code=201, tags=['administration'])
async def deposer_source(request: Request, fichier: str = Query(..., max_length=200, description='nom d\'origine du fichier'),
                         p: Projet = Depends(projet_de)):
    """Dépose un PDF dans sources/ (corps de la requête : le fichier, Content-Type application/pdf) et renvoie
    son profil et une proposition d'entrée pour corpus.json, à vérifier avant de déclarer le document."""
    if request.headers.get('content-type', '').split(';')[0].strip() != 'application/pdf':
        raise HTTPException(415, 'Envoyer le fichier avec le type application/pdf.')
    try:
        nom = await sources.enregistrer(p, fichier, request.stream())
    except FileExistsError as e:
        raise HTTPException(409, f'Un fichier sources/{e} existe déjà dans ce projet.')
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _profil(p, nom)


def _profil(p: Projet, nom: str) -> dict:
    try:
        c = sources.chemin(p, nom)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not c.exists():
        raise HTTPException(404, f'Fichier inconnu : sources/{nom}')
    try:
        r = profil.profiler(c)
    except Exception as e:                                   # PDF illisible : le dire plutôt qu'une erreur 500
        raise HTTPException(422, f'PDF illisible : {e}')
    return dict(fichier=f'sources/{nom}', profil=r)


@pr.get('/sources/{fichier}/profil', tags=['administration'])
def profil_source(fichier: str, p: Projet = Depends(projet_de)):
    """Profil d'un PDF déjà déposé dans sources/ et proposition d'entrée pour corpus.json."""
    return _profil(p, fichier)


@pr.delete('/sources/{fichier}', status_code=204, tags=['administration'])
def retirer_source(fichier: str, p: Projet = Depends(projet_de)):
    """Supprime un PDF déposé mais pas déclaré (annulation d'un ajout) ; 409 s'il est déclaré."""
    try:
        sources.retirer(p, fichier)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except FileNotFoundError:
        raise HTTPException(404, f'Fichier inconnu : sources/{fichier}')
    except KeyError as e:
        raise HTTPException(409, e.args[0])


@pr.get('/documents/{doc_id}/fiche', tags=['administration'])
def fiche_document(doc_id: str, p: Projet = Depends(projet_de)):
    """Fiche du document telle que déclarée dans corpus.json (à modifier depuis la page des projets)."""
    try:
        return sources.fiche(p, doc_id)
    except KeyError:
        raise HTTPException(404, f'Document inconnu : {doc_id}')


@pr.put('/documents/{doc_id}', tags=['administration'])
def modifier_document(doc_id: str, d: NouveauDocument, p: Projet = Depends(projet_de)):
    """Corrige la fiche d'un document. Si l'identifiant change, l'ancien est retiré de la base (ses passages
    seront réingérés sous le nouveau : les citations changent). Réingérer ensuite : tâche « ajout »."""
    if d.extracteur not in sources.extracteurs(p):
        raise HTTPException(422, f'Extracteur inconnu : {d.extracteur}')
    entree = d.model_dump()
    entree['famille'] = (entree['famille'] or '').strip() or None
    try:
        e = sources.modifier(p, doc_id, entree)
    except LookupError:
        raise HTTPException(404, f'Document inconnu : {doc_id}')
    except KeyError as x:
        raise HTTPException(409, x.args[0])
    except FileNotFoundError:
        raise HTTPException(422, f'Fichier absent du projet : {d.fichier}')
    retires = 0
    if d.id != doc_id and p.db.exists():
        from .ingestion import retirer_document
        with base(p) as cx:
            retires = retirer_document(cx, doc_id)
    return dict(fiche=e, identifiant_change=d.id != doc_id, passages_retires=retires)


@pr.post('/documents', status_code=201, tags=['administration'])
def declarer_document(d: NouveauDocument, p: Projet = Depends(projet_de)):
    """Déclare un document déposé (ajout à corpus.json). L'ingérer ensuite : tâche « ajout »."""
    if d.extracteur not in sources.extracteurs(p):
        raise HTTPException(422, f'Extracteur inconnu : {d.extracteur}')
    entree = d.model_dump()
    entree['famille'] = (entree['famille'] or '').strip() or None
    try:
        return sources.declarer(p, entree)
    except KeyError as e:
        raise HTTPException(409, e.args[0])
    except FileNotFoundError:
        raise HTTPException(422, f'Fichier absent du projet : {d.fichier}')


@app.get('/projets', tags=['administration'])
def projets():
    """Les projets de projets/, avec leur état (documents, passages, fraîcheur de l'index et de la carte)."""
    return [etat.resume(p) for p in projet.lister()]


@app.post('/projets', status_code=201, tags=['administration'])
def creer_projet(n: NouveauProjet):
    """Crée un projet vide dans projets/ ; 409 si le dossier existe déjà."""
    try:
        p = projet.creer(n.nom, n.titre.strip(), n.langue)
    except FileExistsError:
        raise HTTPException(409, f'Le dossier projets/{n.nom} existe déjà.')
    return etat.resume(p)


@pr.get('', tags=['administration'])
def projet_etat(p: Projet = Depends(projet_de)):
    return etat.resume(p)


@pr.get('/taches', tags=['administration'])
def liste_taches(p: Projet = Depends(projet_de)):
    return taches.lister(p)


@pr.post('/taches', status_code=202, tags=['administration'])
def lancer_tache(l: Lancement, p: Projet = Depends(projet_de)):
    """Lance une action d'administration en tâche de fond (processus séparé) ; 409 si une tâche tourne déjà."""
    try:
        inconnus = set(l.documents) - {e['id'] for e in p.corpus()}
        if inconnus:
            raise HTTPException(422, f"Documents inconnus : {', '.join(sorted(inconnus))}")
        return taches.lancer(p, l.action, l.documents)
    except taches.TacheEnCours as e:
        raise HTTPException(409, f'Une tâche est déjà en cours pour ce projet : {e}')


@pr.get('/taches/{ident}', tags=['administration'])
def tache(ident: str, lignes: int = Query(200, ge=1, le=5000), p: Projet = Depends(projet_de)):
    """État d'une tâche et fin de son journal."""
    try:
        return taches.lire(p, ident, lignes)
    except KeyError:
        raise HTTPException(404, f'Tâche inconnue : {ident}')


# ───────────── Pages ─────────────
def _page(nom_fichier: str, p: Projet | None = None) -> str:
    page = (PAGES / nom_fichier).read_text(encoding='utf-8')
    if p:
        import html
        page = page.replace('__TITRE__', html.escape(p.titre())).replace('__NOM__', p.nom)
    return page


@app.get('/', response_class=HTMLResponse, include_in_schema=False)
def page_projets():
    """Page d'accueil : les projets, leur état et les actions d'administration."""
    return _page('projets.html')


@pr.get('/essai', response_class=HTMLResponse, include_in_schema=False)
def essai(p: Projet = Depends(projet_de)):
    """Page de test de pertinence : plein texte et recherche par le sens côte à côte, avec jugements."""
    return _page('essai.html', p)


@pr.get('/carte', include_in_schema=False)
def carte(p: Projet = Depends(projet_de)):
    """Carte 3D des passages du projet (fichier produit par l'action « carte »)."""
    if not p.carte.exists():
        return HTMLResponse(_page('carte-absente.html', p), status_code=404)
    return FileResponse(p.carte, media_type='text/html')


app.include_router(pr)
