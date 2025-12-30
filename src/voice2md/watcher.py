from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

from voice2md.config import AppConfig
from voice2md.pipeline import process_audio_file
from voice2md.state import StateStore, open_state_store
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
        self._state: StateStore = open_state_store(path=cfg.state.path, backend=cfg.state.backend)
        self._processed_sources = self._state.processed_source_snapshots()
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
        if self._processed_sources:
            filtered: list[Path] = []
            for path in candidates:
                key = str(path)
                snap = self._processed_sources.get(key)
                if snap is None:
                    filtered.append(path)
                    continue
                try:
                    st = path.stat()
                except FileNotFoundError:
                    continue
                mtime_ns, size = snap
                if mtime_ns is None or size is None:
                    continue
                if int(st.st_mtime_ns) == int(mtime_ns) and int(st.st_size) == int(size):
                    continue
                self._processed_sources.pop(key, None)
                filtered.append(path)
            candidates = filtered
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
                    try:
                        st = path.stat()
                        self._processed_sources[str(path)] = (int(st.st_mtime_ns), int(st.st_size))
                    except FileNotFoundError:
                        pass
            except Exception:
                log.exception("Failed processing: %s", path)
            finally:
                self._stable.forget(path)
