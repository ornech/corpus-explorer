"""Ingestion des documents du projet courant : couches « document » et « passage ».

Usage :
    python3 -m corpus_explorer.ingestion            # tout le corpus du projet
    python3 -m corpus_explorer.ingestion ID1 ID2    # ces documents seulement (réingérés même inchangés)

Un document déjà ingéré dont le fichier et l'extracteur n'ont pas changé est ignoré. Sinon, ses passages sont
réconciliés (`reconcilier`) : un passage au texte inchangé garde son identifiant.
"""
import hashlib
import importlib
import importlib.util
import sys
from collections import defaultdict

from . import ocr, projet
from .db import connexion, initialiser
from .nettoyage import normaliser, porte_du_sens

FILTRE = '1'                      # version du filtre commun (nettoyage.porte_du_sens)


def sha256(chemin):
    h = hashlib.sha256()
    with open(chemin, 'rb') as f:
        for bloc in iter(lambda: f.read(1 << 16), b''):
            h.update(bloc)
    return h.hexdigest()


def charger_extracteur(nom: str, p: projet.Projet | None = None):
    """Extracteur du projet (projets/<projet>/extracteurs/<nom>.py) s'il existe, sinon celui du moteur."""
    local = (p or projet.courant()).extracteurs / f'{nom}.py'
    if local.exists():
        spec = importlib.util.spec_from_file_location(f'extracteurs_projet.{nom}', local)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(f'corpus_explorer.extracteurs.{nom}')


def ingerer(cx, entree, forcer=False, p: projet.Projet | None = None):
    p = p or projet.courant()
    chemin = p.chemin_source(entree)
    empreinte = sha256(chemin)
    module = charger_extracteur(entree['extracteur'], p)
    # Le filtre commun des faux passages fait partie de la signature : le changer réingère tout le corpus
    extracteur = f"{module.NOM} v{module.VERSION} · filtre v{FILTRE}"
    options = dict(entree.get('options', {}))
    refaire_ocr = options.pop('ocr', False)
    if refaire_ocr:                                    # texte tiré d'une copie à la reconnaissance refaite
        extracteur += ' · ocr'

    existant = cx.execute('SELECT sha256, extracteur FROM document WHERE id = ?', (entree['id'],)).fetchone()
    if existant and existant['sha256'] == empreinte and existant['extracteur'] == extracteur and not forcer:
        return entree['id'], 'inchangé', None, None

    source = ocr.refaire(p, chemin, empreinte, entree.get('langue')) if refaire_ocr else chemin
    passages = [x for x in module.extraire(str(source), **options) if porte_du_sens(x['texte'])]
    with cx:
        cx.execute('''INSERT INTO document (id, titre, editeur, annee, version, langue, url, fichier,
                                            sha256, licence, diffusion, extracteur)
                      VALUES (:id, :titre, :editeur, :annee, :version, :langue, :url, :fichier,
                              :sha256, :licence, :diffusion, :extracteur)
                      ON CONFLICT(id) DO UPDATE SET titre=excluded.titre, editeur=excluded.editeur,
                        annee=excluded.annee, version=excluded.version, langue=excluded.langue,
                        url=excluded.url, fichier=excluded.fichier, sha256=excluded.sha256,
                        licence=excluded.licence, diffusion=excluded.diffusion,
                        extracteur=excluded.extracteur, ingere_le=datetime('now')''',
                   dict(entree, url=entree.get('url'), version=entree.get('version'), annee=entree.get('annee'),
                        licence=entree.get('licence'), diffusion=entree.get('diffusion'),
                        sha256=empreinte, extracteur=extracteur))
        bilan = reconcilier(cx, entree['id'], entree['langue'], passages)
    return entree['id'], 'ingéré', len(passages), bilan


def retirer_document(cx, doc_id: str) -> int:
    """Retire un document de la base (passages et index plein texte compris) ; renvoie le nombre de passages retirés."""
    with cx:
        cx.execute('DELETE FROM passage_fts WHERE rowid IN (SELECT id FROM passage WHERE document_id = ?)', (doc_id,))
        n = cx.execute('SELECT count(*) FROM passage WHERE document_id = ?', (doc_id,)).fetchone()[0]
        cx.execute('DELETE FROM document WHERE id = ?', (doc_id,))
    return n


def empreinte_texte(texte: str) -> str:
    return hashlib.sha256(normaliser(texte).encode()).hexdigest()


def reconcilier(cx, doc_id: str, langue: str, passages: list[dict]) -> dict:
    """Remplace les passages du document par `passages` en conservant les identifiants.

    Correspondance : même texte (empreinte) et même volet ; les doublons se répondent dans l'ordre.
    Un passage ancien sans correspondant est supprimé."""
    # Index plein texte vidé d'abord : un passage supprimé plus bas n'y laisse pas de ligne orpheline
    cx.execute('DELETE FROM passage_fts WHERE rowid IN (SELECT id FROM passage WHERE document_id = ?)', (doc_id,))
    anciens = defaultdict(list)
    for r in cx.execute("SELECT id, empreinte, volet FROM passage WHERE document_id = ? AND statut = 'actif' "
                        "ORDER BY ordre", (doc_id,)):
        anciens[(r['empreinte'], r['volet'])].append(r['id'])
    # Ordres provisoires négatifs : la renumérotation ne heurte pas l'unicité (document, ordre)
    cx.execute("UPDATE passage SET ordre = -ordre WHERE document_id = ? AND statut = 'actif'", (doc_id,))
    bilan = dict(conserves=0, nouveaux=0, supprimes=0)
    for k, p in enumerate(passages, 1):
        e = empreinte_texte(p['texte'])
        valeurs = (k, p['page'], p['section'], p['sous_section'], p['ref_externe'], p['type'], langue, p['texte'])
        if anciens[(e, p['volet'])]:
            pid = anciens[(e, p['volet'])].pop(0)
            cx.execute('''UPDATE passage SET ordre=?, page=?, section=?, sous_section=?, ref_externe=?, type=?,
                          langue=?, texte=? WHERE id = ?''', valeurs + (pid,))
            bilan['conserves'] += 1
        else:
            cx.execute('''INSERT INTO passage (ordre, page, section, sous_section, ref_externe, type, langue,
                                               texte, document_id, volet, empreinte)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)''', valeurs + (doc_id, p['volet'], e))
            bilan['nouveaux'] += 1
    for vieux in (pid for ids in anciens.values() for pid in ids):
        cx.execute('DELETE FROM passage WHERE id = ?', (vieux,))
        bilan['supprimes'] += 1
    # Index plein texte : les passages actifs du document
    cx.executemany('INSERT INTO passage_fts (rowid, texte) VALUES (?, ?)',
                   [(r['id'], normaliser(r['texte'])) for r in cx.execute(
                       "SELECT id, texte FROM passage WHERE document_id = ? AND statut = 'actif'", (doc_id,))])
    return bilan


def main(ids):
    p = projet.courant()
    cx = connexion()
    initialiser(cx)
    print(f'[projet] {p.titre()} — {p.dossier}')
    ingeres = []
    for entree in p.corpus():
        if ids and entree['id'] not in ids:
            continue
        doc, etat, nb, bilan = ingerer(cx, entree, forcer=bool(ids), p=p)
        detail = '' if not bilan or not bilan['conserves'] else ' (' + ', '.join(f'{n} {k}' for k, n in bilan.items() if n) + ')'
        print(f"{doc:26} {etat}{'' if nb is None else f' — {nb} passages'}{detail}")
        if etat == 'ingéré':
            ingeres.append(doc)
    # Contrôle de qualité des documents (ré)ingérés : faux passages, parasites, pages, initiales, bandeaux
    if ingeres:
        from .controle import afficher_qualite, qualite
        afficher_qualite(qualite(cx, ingeres), ingeres)


if __name__ == '__main__':
    main(sys.argv[1:])
