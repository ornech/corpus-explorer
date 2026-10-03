-- corpus-explorer — schéma SQLite d'un projet
-- Couches : document → passage (texte fidèle, sourcé à la page). Les couches d'analyse viendront au-dessus.
-- Règle d'accès : seuls l'API et les commandes d'administration ouvrent cette base.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;   -- version du schéma, vérifiée par db.initialiser()

-- ───────────────────────── 1. DOCUMENT ─────────────────────────
CREATE TABLE IF NOT EXISTS document (
    id          TEXT PRIMARY KEY,              -- EDITEUR-SUJET-ANNEE, ex. OMS-RAPPORT-2024
    titre       TEXT NOT NULL,
    editeur     TEXT NOT NULL,
    annee       INTEGER,
    version     TEXT,
    langue      TEXT NOT NULL,                 -- BCP-47 : fr, en…
    url         TEXT,
    fichier     TEXT NOT NULL,                 -- relatif au dossier du projet
    sha256      TEXT NOT NULL,                 -- détecte une source modifiée
    licence     TEXT,                          -- à renseigner : NULL = non vérifiée
    diffusion   TEXT,                          -- public, restreint…
    extracteur  TEXT NOT NULL,                 -- nom + version de l'extracteur
    ingere_le   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ───────────────────────── 2. PASSAGE (texte fidèle) ─────────────────────────
CREATE TABLE IF NOT EXISTS passage (
    id           INTEGER PRIMARY KEY,
    document_id  TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    ordre        INTEGER NOT NULL,             -- ordre de lecture dans le document
    page         TEXT,                         -- numéro imprimé (ou rang dans le PDF à défaut)
    section      TEXT,                         -- chapitre, partie…
    sous_section TEXT,
    volet        TEXT,                         -- colonne ou point de vue, si le document en a
    ref_externe  TEXT,                         -- identifiant officiel (article, mesure…)
    type         TEXT NOT NULL CHECK (type IN
                   ('texte','titre','temoignage','note','ligne-tableau','liste')),
    langue       TEXT NOT NULL,
    texte        TEXT NOT NULL,
    empreinte    TEXT NOT NULL,                -- sha256 du texte normalisé : identité du passage à la ré-extraction
    statut       TEXT NOT NULL DEFAULT 'actif'
                   CHECK (statut IN ('actif','retire'))
);
-- Ordre de lecture unique parmi les passages actifs
CREATE UNIQUE INDEX IF NOT EXISTS ux_passage_ordre ON passage(document_id, ordre) WHERE statut = 'actif';
CREATE INDEX IF NOT EXISTS ix_passage_doc ON passage(document_id, section);

-- Recherche plein texte : trigrammes (SQLite ≥ 3.34). Le texte indexé est normalisé en Python
-- (minuscules, sans accents) par l'ingestion : l'option remove_diacritics du tokenizer trigram
-- n'existe qu'à partir de SQLite 3.45.
-- Pas de trigger : seule l'ingestion écrit les passages et tient l'index à jour.
CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(texte, tokenize = 'trigram');
