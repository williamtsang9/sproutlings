"""Repository: every database read/write goes through this module so the
API layer and tests share one audited code path."""
import json
import sqlite3
from typing import Optional

from . import config


class DuplicateContentError(Exception):
    """Raised when a content hash already exists for this child."""


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- children ------------------------------------------------------
    def add_child(self, name: str, age: int, default_grade: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("Child name must not be empty.")
        if default_grade not in config.GRADES:
            raise ValueError(f"Unknown grade: {default_grade!r}")
        cur = self.conn.execute(
            "INSERT INTO children (name, age, default_grade) VALUES (?, ?, ?)",
            (name, age, default_grade),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_child(self, child_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM children WHERE id = ?", (child_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_children(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM children ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- packets ---------------------------------------------------------
    def save_packet(self, child_id: int, kind: str, field: Optional[str],
                    grade: str, level: str, content: dict,
                    content_hash: str) -> int:
        """Insert a packet and its uniqueness fingerprint atomically.

        Raises DuplicateContentError if this exact content already exists
        for the child — the generation loop catches it and reseeds.
        """
        try:
            with self.conn:  # one transaction: both rows or neither
                cur = self.conn.execute(
                    """INSERT INTO packets
                       (child_id, kind, field, grade, level, content_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (child_id, kind, field, grade, level,
                     json.dumps(content, sort_keys=True)),
                )
                packet_id = cur.lastrowid
                self.conn.execute(
                    """INSERT INTO worksheet_hashes
                       (child_id, content_hash, packet_id) VALUES (?, ?, ?)""",
                    (child_id, content_hash, packet_id),
                )
        except sqlite3.IntegrityError as e:
            raise DuplicateContentError(content_hash) from e
        return packet_id

    def hash_exists(self, child_id: int, content_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM worksheet_hashes WHERE child_id=? AND content_hash=?",
            (child_id, content_hash),
        ).fetchone()
        return row is not None

    def get_packet(self, packet_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM packets WHERE id = ?", (packet_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["content"] = json.loads(d.pop("content_json"))
        return d

    def list_packets(self, child_id: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, kind, field, grade, level, status,
                      created_at, completed_at
               FROM packets WHERE child_id = ? ORDER BY id DESC""",
            (child_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_packet_status(self, packet_id: int, status: str) -> None:
        if status not in ("needs_review", "approved", "completed"):
            raise ValueError(f"Invalid status: {status!r}")
        completed_at = "datetime('now')" if status == "completed" else "NULL"
        self.conn.execute(
            f"""UPDATE packets SET status = ?,
                completed_at = {completed_at} WHERE id = ?""",
            (status, packet_id),
        )
        self.conn.commit()

    # --- stats (the per-child dashboard) ---------------------------------
    def child_stats(self, child_id: int) -> dict:
        """Generated and completed packet counts per field, plus latest
        test averages — e.g. 'Jon has generated 5 Mathematics packets,
        completed 3'."""
        gen = self.conn.execute(
            """SELECT COALESCE(field, '(test)') AS field,
                      COUNT(*) AS generated,
                      SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)
                          AS completed
               FROM packets WHERE child_id = ? GROUP BY field""",
            (child_id,),
        ).fetchall()
        scores = self.conn.execute(
            """SELECT field,
                      ROUND(AVG(1.0 * correct / total), 3) AS avg_score,
                      COUNT(*) AS tests_taken
               FROM (SELECT field, correct, total,
                            ROW_NUMBER() OVER
                              (PARTITION BY field ORDER BY recorded_at DESC)
                              AS rn
                     FROM test_scores WHERE child_id = ?)
               WHERE rn <= ?
               GROUP BY field""",
            (child_id, config.ADAPTIVE_WINDOW),
        ).fetchall()
        return {
            "fields": [dict(r) for r in gen],
            "recent_scores": [dict(r) for r in scores],
        }

    # --- test scores ------------------------------------------------------
    def record_test_scores(self, packet_id: int, child_id: int,
                           per_field: dict[str, tuple[int, int]]) -> None:
        """per_field maps field -> (correct, total)."""
        for field, (correct, total) in per_field.items():
            if field not in config.FIELDS:
                raise ValueError(f"Unknown field: {field!r}")
            if not (0 <= correct <= total) or total <= 0:
                raise ValueError(
                    f"Invalid score {correct}/{total} for {field}")
        with self.conn:
            for field, (correct, total) in per_field.items():
                self.conn.execute(
                    """INSERT INTO test_scores
                       (packet_id, child_id, field, correct, total)
                       VALUES (?, ?, ?, ?, ?)""",
                    (packet_id, child_id, field, correct, total),
                )

    def recent_scores(self, child_id: int) -> dict[str, float]:
        """Average of the last ADAPTIVE_WINDOW scores per field, 0.0–1.0."""
        rows = self.conn.execute(
            """SELECT field, AVG(1.0 * correct / total) AS avg_score
               FROM (SELECT field, correct, total,
                            ROW_NUMBER() OVER
                              (PARTITION BY field ORDER BY recorded_at DESC)
                              AS rn
                     FROM test_scores WHERE child_id = ?)
               WHERE rn <= ? GROUP BY field""",
            (child_id, config.ADAPTIVE_WINDOW),
        ).fetchall()
        return {r["field"]: r["avg_score"] for r in rows}

    def recent_topics(self, child_id: int, field: str, limit: int = 10) -> list[str]:
        """Topic strings from the child's recent packets in a field — fed to
        the LLM as 'avoid these' so content stays fresh beyond hash-level
        uniqueness."""
        rows = self.conn.execute(
            """SELECT content_json FROM packets
               WHERE child_id = ? AND field = ?
               ORDER BY id DESC LIMIT ?""",
            (child_id, field, limit),
        ).fetchall()
        topics: list[str] = []
        for r in rows:
            content = json.loads(r["content_json"])
            for sheet in content.get("sheets", []):
                t = sheet.get("topic")
                if t and t not in topics:
                    topics.append(t)
        return topics
