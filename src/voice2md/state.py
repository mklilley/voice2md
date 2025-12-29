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
    source_mtime_ns: int | None
    source_size: int | None
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
              source_mtime_ns INTEGER,
              source_size INTEGER,
              archive_path TEXT,
              topic_file TEXT,
              codex_status TEXT,
              error TEXT
            )
            """
        )
        self._ensure_columns(cur)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_processed_files_source ON processed_files (source_path)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_processed_files_source_stat ON processed_files (source_path, source_mtime_ns, source_size)"
        )
        self._conn.commit()

    def _ensure_columns(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(processed_files)")
        existing = {row[1] for row in cur.fetchall()}
        if "source_mtime_ns" not in existing:
            cur.execute("ALTER TABLE processed_files ADD COLUMN source_mtime_ns INTEGER")
        if "source_size" not in existing:
            cur.execute("ALTER TABLE processed_files ADD COLUMN source_size INTEGER")

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
            source_mtime_ns=row["source_mtime_ns"],
            source_size=row["source_size"],
            archive_path=row["archive_path"],
            topic_file=row["topic_file"],
            codex_status=row["codex_status"],
            error=row["error"],
        )

    def is_processed(self, sha256: str) -> bool:
        rec = self.get(sha256)
        return rec is not None and rec.status == "processed"

    def is_source_processed(
        self,
        source_path: Path,
        *,
        source_mtime_ns: int | None = None,
        source_size: int | None = None,
    ) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT status, source_mtime_ns, source_size
            FROM processed_files
            WHERE source_path = ? AND status = 'processed'
            ORDER BY processed_at DESC
            LIMIT 1
            """,
            (str(source_path),),
        )
        row = cur.fetchone()
        if row is None:
            return False
        mtime_ns = row["source_mtime_ns"]
        size = row["source_size"]
        if mtime_ns is None or size is None:
            return True
        if source_mtime_ns is None or source_size is None:
            return True
        return int(mtime_ns) == int(source_mtime_ns) and int(size) == int(source_size)

    def processed_source_snapshots(self) -> dict[str, tuple[int | None, int | None]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT source_path, source_mtime_ns, source_size, processed_at
            FROM processed_files
            WHERE status='processed' AND source_path IS NOT NULL
            """
        )
        latest: dict[str, tuple[float, int | None, int | None]] = {}
        for row in cur.fetchall():
            p = row["source_path"]
            if not p:
                continue
            processed_at = float(row["processed_at"] or 0.0)
            mtime_ns = row["source_mtime_ns"]
            size = row["source_size"]
            prev = latest.get(p)
            if prev is None or processed_at >= prev[0]:
                latest[p] = (processed_at, mtime_ns, size)
        return {p: (mtime_ns, size) for p, (_t, mtime_ns, size) in latest.items()}

    def mark_in_progress(
        self,
        sha256: str,
        source_path: Path,
        *,
        source_mtime_ns: int | None,
        source_size: int | None,
        force: bool = False,
    ) -> None:
        now = time.time()
        cur = self._conn.cursor()
        if force:
            cur.execute(
                """
                INSERT INTO processed_files (sha256, status, started_at, source_path, source_mtime_ns, source_size)
                VALUES (?, 'in_progress', ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                  status='in_progress',
                  started_at=excluded.started_at,
                  source_path=excluded.source_path,
                  source_mtime_ns=excluded.source_mtime_ns,
                  source_size=excluded.source_size,
                  error=NULL
                """,
                (sha256, now, str(source_path), source_mtime_ns, source_size),
            )
        else:
            cur.execute(
                """
                INSERT INTO processed_files (sha256, status, started_at, source_path, source_mtime_ns, source_size)
                VALUES (?, 'in_progress', ?, ?, ?, ?)
                ON CONFLICT(sha256) DO NOTHING
                """,
                (sha256, now, str(source_path), source_mtime_ns, source_size),
            )
        self._conn.commit()

    def mark_processed(
        self,
        sha256: str,
        *,
        archive_path: Path | None,
        topic_file: Path | None,
        codex_status: str | None,
        source_path: Path | None = None,
        source_mtime_ns: int | None = None,
        source_size: int | None = None,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO processed_files (
              sha256, status, started_at, processed_at, source_path, source_mtime_ns, source_size, archive_path, topic_file, codex_status, error
            )
            VALUES (?, 'processed', NULL, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(sha256) DO UPDATE SET
              status='processed',
              processed_at=excluded.processed_at,
              source_path=COALESCE(excluded.source_path, source_path),
              source_mtime_ns=COALESCE(excluded.source_mtime_ns, source_mtime_ns),
              source_size=COALESCE(excluded.source_size, source_size),
              archive_path=excluded.archive_path,
              topic_file=excluded.topic_file,
              codex_status=excluded.codex_status,
              error=NULL
            """,
            (
                sha256,
                time.time(),
                str(source_path) if source_path else None,
                source_mtime_ns,
                source_size,
                str(archive_path) if archive_path else None,
                str(topic_file) if topic_file else None,
                codex_status,
            ),
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
