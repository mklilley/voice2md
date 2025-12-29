from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

from voice2md.config import AppConfig
from voice2md.pipeline import process_audio_file
from voice2md.state import StateStore
from voice2md.stable import StableFileTracker

log = logging.getLogger(__name__)


def _is_candidate(path: Path, allowed_exts: tuple[str, ...]) -> bool:
    if not path.is_file():
        return False

    name = path.name
    if name.startswith("."):
        return False
    lowered = name.lower()
    if lowered.startswith(".syncthing."):
        return False
    if lowered.endswith((".tmp", ".part", ".partial")):
        return False
    if path.suffix.lower() not in {e.lower() for e in allowed_exts}:
        return False
    return True


def list_candidates(inbox_dir: Path, allowed_exts: tuple[str, ...]) -> list[Path]:
    if not inbox_dir.exists():
        return []
    out: list[Path] = []
    for path in inbox_dir.rglob("*"):
        try:
            if _is_candidate(path, allowed_exts):
                out.append(path)
        except OSError:
            continue
    return out


class Watcher:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._stop = False
        self._state = StateStore(cfg.paths.state_db_path)
        self._stable = StableFileTracker(stable_seconds=cfg.processing.stable_seconds)

    def close(self) -> None:
        self._state.close()

    def stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())

        log.info("Watching inbox: %s", self._cfg.paths.inbox_audio_dir)
        while not self._stop:
            self.run_once()
            time.sleep(self._cfg.processing.poll_interval_seconds)

        log.info("Watcher stopped")

    def run_once(self) -> None:
        candidates = list_candidates(
            self._cfg.paths.inbox_audio_dir, self._cfg.processing.allowed_extensions
        )
        if not candidates:
            return

        stable = self._stable.observe(candidates)
        def _mtime_or_zero(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except FileNotFoundError:
                return 0.0

        stable.sort(key=_mtime_or_zero)

        for path in stable:
            try:
                outcome = process_audio_file(self._cfg, audio_path=path, state=self._state)
                if outcome:
                    log.info(
                        "Processed: %s -> %s (codex=%s)",
                        path.name,
                        outcome.topic_file,
                        outcome.codex_status,
                    )
            except Exception:
                log.exception("Failed processing: %s", path)
            finally:
                self._stable.forget(path)
