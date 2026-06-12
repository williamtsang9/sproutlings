"""SQLite persistence layer. Stdlib sqlite3 only — no ORM dependency.

The database file lives next to the repo (config.DB_PATH) so all child
profiles, packet history, completion counts and test scores survive
restarts of the localhost app.
"""
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS children (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    age         INTEGER NOT NULL CHECK (age BETWEEN 1 AND 25),
    default_grade TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS packets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id    INTEGER NOT NULL REFERENCES children(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('worksheet', 'test')),
    field       TEXT,                -- NULL for multi-field test packets
    grade       TEXT NOT NULL,
    level       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'needs_review'
                CHECK (status IN ('needs_review', 'approved', 'completed')),
    content_json TEXT NOT NULL,      -- full worksheet/test content
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Hard uniqueness guarantee: one row per (child, content fingerprint).
-- The UNIQUE constraint makes a duplicate insert impossible even under
-- concurrent requests; generation retries with a new seed on collision.
CREATE TABLE IF NOT EXISTS worksheet_hashes (
    child_id    INTEGER NOT NULL REFERENCES children(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    packet_id   INTEGER NOT NULL REFERENCES packets(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (child_id, content_hash)
);

-- Per-field result of a graded test packet. One test packet produces one
-- row per field it covered; these drive the adaptive engine.
CREATE TABLE IF NOT EXISTS test_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    packet_id   INTEGER NOT NULL REFERENCES packets(id) ON DELETE CASCADE,
    child_id    INTEGER NOT NULL REFERENCES children(id) ON DELETE CASCADE,
    field       TEXT NOT NULL,
    correct     INTEGER NOT NULL CHECK (correct >= 0),
    total       INTEGER NOT NULL CHECK (total > 0),
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (correct <= total)
);

CREATE INDEX IF NOT EXISTS idx_packets_child   ON packets(child_id, field);
CREATE INDEX IF NOT EXISTS idx_scores_child    ON test_scores(child_id, field, recorded_at);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
