"""SQLite-Zustandspeicher: Content-Hash pro Note (vermeidet Re-Embedding
von unveraenderten Notes). Der Qdrant-Zustand selbst ist die Source of
Truth; dieses DB ist nur ein Performance-Cache und verliert bei Verlust
des Pod-Volumes schlicht (=> einmaliger Full-Reindex beim naechsten Lauf).
"""

from __future__ import annotations

import sqlite3
import threading


class State:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS notes (
                   note_id TEXT PRIMARY KEY,
                   content_hash TEXT NOT NULL,
                   chunks INTEGER NOT NULL DEFAULT 0,
                   updated_at TEXT
               )"""
        )
        self._db.commit()

    def hash(self, note_id: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT content_hash FROM notes WHERE note_id = ?", (note_id,)
            ).fetchone()
        return row[0] if row else None

    def set(self, note_id: str, content_hash: str, chunks: int, updated_at: str) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO notes (note_id, content_hash, chunks, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(note_id) DO UPDATE SET
                     content_hash = excluded.content_hash,
                     chunks = excluded.chunks,
                     updated_at = excluded.updated_at""",
                (note_id, content_hash, chunks, updated_at),
            )
            self._db.commit()

    def delete(self, note_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()
