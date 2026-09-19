"""SQLite trace persistence with bounded retention and legacy JSONL import."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def load_traces(path: Path, *, limit: int) -> list[dict[str, Any]]:
    """Load recent traces, importing legacy records on first use.

    Args:
        path: Database location.
        limit: Maximum number of records.

    Returns:
        Detached traces ordered by creation sequence.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    first = not path.exists()
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS traces (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, body TEXT NOT NULL, size INTEGER NOT NULL)"
        )
        if "size" not in {
            column[1] for column in db.execute("PRAGMA table_info(traces)")
        }:
            db.execute("ALTER TABLE traces ADD COLUMN size INTEGER NOT NULL DEFAULT 0")
            db.execute("UPDATE traces SET size = length(CAST(body AS BLOB))")
    if first:
        legacy = path.with_name("traces.jsonl")
        if legacy.is_file():
            with legacy.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if isinstance(row, dict) and row.get("id"):
                        upsert_trace(path, row, limit=limit)
    with closing(sqlite3.connect(path)) as db, db:
        rows = db.execute(
            "SELECT body FROM traces ORDER BY seq DESC LIMIT ?", (limit,)
        ).fetchall()
    return [json.loads(row[0]) for row in reversed(rows)]


def upsert_trace(path: Path, trace: dict[str, Any], *, limit: int) -> None:
    """Persist a single trace and bound total stored content to 64 MiB.

    Args:
        path: Initialized database path.
        trace: Detached trace.
        limit: Maximum retained records.
    """
    body = json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO traces(id, body, size) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body, size=excluded.size",
            (trace["id"], body, len(body.encode("utf-8"))),
        )
        db.execute(
            "DELETE FROM traces WHERE seq NOT IN (SELECT seq FROM traces ORDER BY seq DESC LIMIT ?)",
            (limit,),
        )
        size = db.execute("SELECT coalesce(sum(size), 0) FROM traces").fetchone()[0]
        while size > 64 * 1024 * 1024:
            seq, length = db.execute(
                "SELECT seq, size FROM traces ORDER BY seq LIMIT 1"
            ).fetchone()
            db.execute("DELETE FROM traces WHERE seq = ?", (seq,))
            size -= length


def clear_file(path: Path) -> None:
    """Clear stored records while retaining the database schema.

    Args:
        path: Database path.
    """
    if path.is_file():
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DELETE FROM traces")
