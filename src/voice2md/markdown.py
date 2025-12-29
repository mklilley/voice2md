from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_SECTION_RE = re.compile(r"(?m)^## (Voice Dump|AI Commentary) — .*$")


def sanitize_topic(topic: str, *, fallback: str = "Untitled") -> str:
    topic = topic.strip()
    topic = re.sub(r"[\\/]+", "-", topic)
    topic = re.sub(r"[:*?\"<>|]", "", topic)
    topic = re.sub(r"\s+", " ", topic).strip()
    return topic or fallback


def topic_file_path(topics_dir: Path, topic: str) -> Path:
    return topics_dir / f"{sanitize_topic(topic)}.md"


def ensure_topic_file(topic_file: Path, *, topic_title: str) -> bool:
    if topic_file.exists():
        return False
    topic_file.parent.mkdir(parents=True, exist_ok=True)
    topic_file.write_text(f"# {topic_title}\n\n", encoding="utf-8")
    return True


def _cleanup_transcript(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def voice_dump_marker(sha256: str) -> str:
    return f"<!-- voice2md:sha256={sha256} -->"


def notebook_contains_sha256(topic_file: Path, sha256: str) -> bool:
    if not topic_file.exists():
        return False
    try:
        text = topic_file.read_text(encoding="utf-8")
    except OSError:
        return False
    return voice_dump_marker(sha256) in text


def format_voice_dump_section(
    *,
    dumped_at: datetime,
    source_audio: str,
    mode: str,
    transcript: str,
    audio_sha256: str | None = None,
) -> str:
    transcript = _cleanup_transcript(transcript)
    ts = dumped_at.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"## Voice Dump — {ts}",
        f"**Source audio:** {source_audio}",
        f"**Mode:** {mode}",
    ]
    if audio_sha256:
        lines.append(voice_dump_marker(audio_sha256))
    lines += [
        "",
        transcript,
        "",
    ]
    return "\n".join(lines)


def append_block(topic_file: Path, block: str, *, include_separator: bool) -> None:
    block = block.rstrip("\n") + "\n"

    prefix = ""
    if topic_file.exists() and topic_file.stat().st_size > 0:
        with topic_file.open("rb") as f:
            f.seek(max(0, topic_file.stat().st_size - 2))
            tail = f.read()
        if not tail.endswith(b"\n"):
            prefix += "\n"
        if include_separator:
            prefix += "\n---\n\n"

    with topic_file.open("a", encoding="utf-8") as f:
        if prefix:
            f.write(prefix)
        f.write(block)


@dataclass(frozen=True)
class NotebookContext:
    markdown: str


@dataclass(frozen=True)
class LatestSections:
    latest_voice_dump: str | None
    latest_ai_commentary: str | None
    last_section_kind: str | None


def extract_latest_sections(topic_file: Path) -> LatestSections:
    if not topic_file.exists():
        return LatestSections(latest_voice_dump=None, latest_ai_commentary=None, last_section_kind=None)

    text = topic_file.read_text(encoding="utf-8")
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return LatestSections(latest_voice_dump=None, latest_ai_commentary=None, last_section_kind=None)

    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        kind = m.group(1)
        sections.append((kind, text[start:end].strip()))

    latest_voice = next((s for k, s in reversed(sections) if k == "Voice Dump"), None)
    latest_ai = next((s for k, s in reversed(sections) if k == "AI Commentary"), None)
    last_kind = sections[-1][0] if sections else None
    return LatestSections(latest_voice_dump=latest_voice, latest_ai_commentary=latest_ai, last_section_kind=last_kind)


def extract_context(
    topic_file: Path,
    *,
    voice_dumps: int,
    ai_commentaries: int,
    max_chars: int,
    skip_latest_voice_dump: bool = False,
) -> NotebookContext:
    if not topic_file.exists():
        return NotebookContext(markdown="")

    text = topic_file.read_text(encoding="utf-8")
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return NotebookContext(markdown="")

    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        kind = m.group(1)
        sections.append((kind, text[start:end].strip()))

    selected_rev: list[str] = []
    remaining_voice = voice_dumps
    remaining_ai = ai_commentaries
    total = 0
    sep_len = len("\n\n---\n\n")
    skipped_voice = False

    for kind, content in reversed(sections):
        if kind == "Voice Dump" and skip_latest_voice_dump and not skipped_voice:
            skipped_voice = True
            continue
        if kind == "Voice Dump" and remaining_voice <= 0:
            continue
        if kind == "AI Commentary" and remaining_ai <= 0:
            continue

        block = content.strip()
        block_len = len(block) + (sep_len if selected_rev else 0)
        if selected_rev and (total + block_len) > max_chars:
            break

        selected_rev.append(block)
        total += block_len
        if kind == "Voice Dump":
            remaining_voice -= 1
        else:
            remaining_ai -= 1
        if remaining_voice <= 0 and remaining_ai <= 0:
            break

    selected = list(reversed(selected_rev))
    return NotebookContext(markdown="\n\n---\n\n".join(selected).strip())
