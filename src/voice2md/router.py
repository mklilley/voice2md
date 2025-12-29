from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_TOPIC_RE = re.compile(r"(?im)^\s*TOPIC\s*:\s*(.+?)\s*$")
_MODE_RE = re.compile(r"(?im)^\s*MODE\s*:\s*(.+?)\s*$")


@dataclass(frozen=True)
class RouteDecision:
    topic: str
    mode: str
    topic_source: str
    mode_source: str


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    if not m:
        return None
    value = m.group(1).strip()
    return value or None


def tokens_from_transcript(transcript: str) -> tuple[str | None, str | None]:
    return _first_match(_TOPIC_RE, transcript), _first_match(_MODE_RE, transcript)


def filename_hints(audio_path: Path) -> tuple[str | None, str | None]:
    """
    Parses `YYYY-MM-DD__Topic__MODE.ext` (and the MODE part is optional).
    """
    name = audio_path.name
    base = name.rsplit(".", 1)[0]
    parts = base.split("__")
    if len(parts) < 2:
        return None, None

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]):
        return None, None

    topic = parts[1].strip() or None
    mode = parts[2].strip() if len(parts) >= 3 else None
    mode = mode or None
    return topic, mode


def _read_override_topic(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return content or None


def decide_route(
    *,
    audio_path: Path,
    transcript: str,
    inbox_topic: str,
    override_topic_file: Path | None = None,
) -> RouteDecision:
    # Priority:
    #   1) Transcript tokens (TOPIC:/MODE:)
    #   2) CURRENT_TOPIC override file (optional extra)
    #   3) Filename hints
    #   4) Fallback INBOX.md
    topic, mode = tokens_from_transcript(transcript)
    topic_source = "transcript" if topic else ""
    mode_source = "transcript" if mode else ""

    if not topic:
        topic = _read_override_topic(override_topic_file)
        if topic:
            topic_source = "override"

    fn_topic, fn_mode = filename_hints(audio_path)
    if not topic and fn_topic:
        topic = fn_topic
        topic_source = "filename"
    if not mode and fn_mode:
        mode = fn_mode
        mode_source = "filename"

    if not topic:
        topic = inbox_topic
        topic_source = "fallback"
    if not mode:
        mode = "unspecified"
        mode_source = "fallback"

    return RouteDecision(
        topic=topic,
        mode=mode,
        topic_source=topic_source,
        mode_source=mode_source,
    )

