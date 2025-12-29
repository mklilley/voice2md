from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileRecord:
    sha256: str
    status: str
    started_at: float | None
    processed_at: float | None
    source_path: str | None
    archive_path: str | None
    topic_file: str | None
    error: str | None
    codex_status: str | None


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_files (
              sha256 TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              started_at REAL,
              processed_at REAL,
              source_path TEXT,
              archive_path TEXT,
              topic_file TEXT,
              codex_status TEXT,
              error TEXT
            )
            """
        )
        self._conn.commit()

    def get(self, sha256: str) -> FileRecord | None:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM processed_files WHERE sha256 = ?", (sha256,))
        row = cur.fetchone()
        if row is None:
            return None
        return FileRecord(
            sha256=row["sha256"],
            status=row["status"],
            started_at=row["started_at"],
            processed_at=row["processed_at"],
            source_path=row["source_path"],
            archive_path=row["archive_path"],
            topic_file=row["topic_file"],
            codex_status=row["codex_status"],
            error=row["error"],
        )

    def is_processed(self, sha256: str) -> bool:
        rec = self.get(sha256)
        return rec is not None and rec.status == "processed"

    def mark_in_progress(self, sha256: str, source_path: Path, *, force: bool = False) -> None:
        now = time.time()
        cur = self._conn.cursor()
        if force:
            cur.execute(
                """
                INSERT INTO processed_files (sha256, status, started_at, source_path)
                VALUES (?, 'in_progress', ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                  status='in_progress',
                  started_at=excluded.started_at,
                  source_path=excluded.source_path,
                  error=NULL
                """,
                (sha256, now, str(source_path)),
            )
        else:
            cur.execute(
                """
                INSERT INTO processed_files (sha256, status, started_at, source_path)
                VALUES (?, 'in_progress', ?, ?)
                ON CONFLICT(sha256) DO NOTHING
                """,
                (sha256, now, str(source_path)),
            )
        self._conn.commit()

    def mark_processed(
        self,
        sha256: str,
        *,
        archive_path: Path | None,
        topic_file: Path | None,
        codex_status: str | None,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO processed_files (
              sha256, status, started_at, processed_at, source_path, archive_path, topic_file, codex_status, error
            )
            VALUES (?, 'processed', NULL, ?, NULL, ?, ?, ?, NULL)
            ON CONFLICT(sha256) DO UPDATE SET
              status='processed',
              processed_at=excluded.processed_at,
              archive_path=excluded.archive_path,
              topic_file=excluded.topic_file,
              codex_status=excluded.codex_status,
              error=NULL
            """,
            (sha256, time.time(), str(archive_path) if archive_path else None, str(topic_file) if topic_file else None, codex_status),
        )
        self._conn.commit()

    def mark_failed(self, sha256: str, error: str) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO processed_files (sha256, status, started_at, processed_at, error)
            VALUES (?, 'failed', NULL, ?, ?)
            ON CONFLICT(sha256) DO UPDATE SET
              status='failed',
              processed_at=excluded.processed_at,
              error=excluded.error
            """,
            (sha256, time.time(), error),
        )
        self._conn.commit()

    def allow_retry_in_progress(self, sha256: str, ttl_seconds: int) -> bool:
        rec = self.get(sha256)
        if rec is None:
            return True
        if rec.status == "processed":
            return False
        if rec.status != "in_progress":
            return True
        if rec.started_at is None:
            return True
        return (time.time() - rec.started_at) > ttl_seconds

    def stats(self) -> dict[str, int]:
        cur = self._conn.cursor()
        cur.execute("SELECT status, COUNT(*) as n FROM processed_files GROUP BY status")
        out = {row["status"]: int(row["n"]) for row in cur.fetchall()}
        out.setdefault("processed", 0)
        out.setdefault("failed", 0)
        out.setdefault("in_progress", 0)
        return out

