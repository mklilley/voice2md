from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def plan_archive_path(
    *,
    source_path: Path,
    archive_root: Path,
    subdir_format: str,
    now: datetime,
) -> Path:
    """
    Returns the destination path under archive_root/subdir_format/, preserving filename.
    If a collision occurs, adds a numeric suffix.
    """
    rel_dir = Path(now.strftime(subdir_format))
    dest_dir = (archive_root / rel_dir).expanduser()

    dest = dest_dir / source_path.name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        for i in range(1, 1000):
            candidate = dest_dir / f"{stem}__{i}{suffix}"
            if not candidate.exists():
                dest = candidate
                break
    return dest


def ensure_archived_copy(*, source_path: Path, dest_path: Path) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        return dest_path

    log.info("Copying audio to archive: %s -> %s", source_path, dest_path)
    shutil.copy2(source_path, dest_path)
    return dest_path


def finalize_archived_move(*, source_path: Path) -> None:
    log.info("Removing original audio from inbox: %s", source_path)
    source_path.unlink(missing_ok=True)

