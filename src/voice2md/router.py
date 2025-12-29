from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_TOPIC_RE = re.compile(r"(?im)^\s*TOPIC\s*:\s*(.+?)\s*$")
_META_LINE_RE = re.compile(r"(?i)^\s*(topic|mode)\s*:\s*.+$")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


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


def tokens_from_transcript(transcript: str) -> str | None:
    return _first_match(_TOPIC_RE, transcript)


def filename_hints(audio_path: Path) -> str | None:
    """
    Parses `<anything>YYYY-MM-DD<topic>.ext`:
      - finds the first `YYYY-MM-DD` in the basename (no extension)
      - treats everything after it as the topic
    """
    base = audio_path.stem
    m = _DATE_RE.search(base)
    if not m:
        return None

    topic = base[m.end() :].strip()
    topic = topic.lstrip(" _-–—:").strip()
    return topic or None


_CLAIMS_PATTERNS = [
    re.compile(r"\bthis proves\b"),
    re.compile(r"\bobviously\b"),
    re.compile(r"\btherefore\b"),
    re.compile(r"\bthus\b"),
    re.compile(r"\bmust be\b"),
    re.compile(r"\bcauses\b"),
    re.compile(r"\bleads to\b"),
    re.compile(r"\bresults in\b"),
    re.compile(r"\bthe real reason is\b"),
]

_MODEL_PATTERNS = [
    re.compile(r"\bmodel\b"),
    re.compile(r"\bframework\b"),
    re.compile(r"\bassumption(s)?\b"),
    re.compile(r"\bmechanism\b"),
    re.compile(r"\bvariable(s)?\b"),
    re.compile(r"\bequation(s)?\b"),
    re.compile(r"\b(let's|lets)\s+define\b"),
    re.compile(r"\boperationali[sz]e\b"),
]

_PREP_FOR_SHARING_PATTERNS = [
    re.compile(r"\bwrite this up\b"),
    re.compile(r"\bfor sharing\b"),
    re.compile(r"\bpublish\b"),
    re.compile(r"\bblog\b"),
    re.compile(r"\bnewsletter\b"),
    re.compile(r"\bpresentation\b"),
]


def _strip_meta_lines(transcript: str) -> str:
    return "\n".join(
        line for line in transcript.splitlines() if not _META_LINE_RE.match(line.strip())
    )


def infer_mode(transcript: str) -> str:
    """
    Infers an epistemic mode from content.

    Modes are used only as a lightweight label in the Markdown header and as a hint to the referee
    prompt; they're not required to be perfect.
    """
    text = _strip_meta_lines(transcript).lower()
    if any(p.search(text) for p in _PREP_FOR_SHARING_PATTERNS):
        return "prep for sharing"
    if any(p.search(text) for p in _CLAIMS_PATTERNS):
        return "claims"
    if any(p.search(text) for p in _MODEL_PATTERNS):
        return "model-forming"
    return "brainstorming"

_STOPWORDS = {
    "a",
    "about",
    "after",
    "again",
    "all",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "back",
    "be",
    "because",
    "been",
    "before",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "even",
    "for",
    "from",
    "get",
    "getting",
    "go",
    "going",
    "got",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "like",
    "lot",
    "me",
    "more",
    "most",
    "my",
    "no",
    "not",
    "now",
    "of",
    "on",
    "one",
    "or",
    "our",
    "out",
    "really",
    "right",
    "said",
    "say",
    "saying",
    "see",
    "so",
    "some",
    "sort",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "to",
    "up",
    "us",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "which",
    "with",
    "would",
    "yeah",
    "you",
    "your",
}


def _title_word(word: str) -> str:
    if word.isupper():
        return word
    if word in {"ai", "ml", "uk", "us"}:
        return word.upper()
    return word.capitalize()


_ABOUT_PHRASE_RE = re.compile(
    r"(?i)\b(?:talk(?:ing)?|think(?:ing)?|reflect(?:ing)?|focus(?:ing)?|rant(?:ing)?)\s+about\s+(.{3,80}?)(?:[.\n\r!?]|$)"
)
_THIS_IS_ABOUT_RE = re.compile(
    r"(?i)\b(?:this\s+is\s+about|the\s+topic\s+is)\s+(.{3,80}?)(?:[.\n\r!?]|$)"
)


def infer_topic(
    transcript: str,
    *,
    dumped_at: datetime | None = None,
    max_words: int = 6,
    max_chars: int = 80,
) -> str:
    """
    Tries to infer a stable, human-usable topic name from transcript content.
    """
    explicit = tokens_from_transcript(transcript)
    if explicit:
        return explicit

    cleaned = _strip_meta_lines(transcript)

    for pattern in (_THIS_IS_ABOUT_RE, _ABOUT_PHRASE_RE):
        m = pattern.search(cleaned)
        if m:
            phrase = m.group(1).strip()
            phrase = re.sub(r"\s+", " ", phrase)
            if phrase:
                return phrase[:max_chars].rstrip()

    words = re.findall(r"[A-Za-z][A-Za-z0-9']+", cleaned.lower())
    positions: dict[str, int] = {}
    freq: dict[str, int] = {}
    for idx, w in enumerate(words):
        w = w.strip("'")
        if not w:
            continue
        if w in _STOPWORDS:
            continue
        if len(w) < 2:
            continue
        positions.setdefault(w, idx)
        freq[w] = freq.get(w, 0) + 1

    ranked = sorted(freq.keys(), key=lambda w: (-freq[w], positions.get(w, 10**9)))
    picked = [_title_word(w) for w in ranked[:max_words]]
    topic = " ".join(picked).strip()
    if topic:
        return topic[:max_chars].rstrip()

    if dumped_at is not None:
        return f"Voice Note {dumped_at:%Y-%m-%d %H:%M}"
    return "Voice Note"


def decide_route(
    *,
    audio_path: Path,
    transcript: str,
    dumped_at: datetime | None = None,
    infer_topic_max_words: int = 6,
    infer_topic_max_chars: int = 80,
) -> RouteDecision:
    # Priority:
    #   1) Filename hints
    #   2) Transcript/topic inference
    fn_topic = filename_hints(audio_path)
    if fn_topic:
        topic = fn_topic
        topic_source = "filename"
    else:
        topic = infer_topic(
            transcript,
            dumped_at=dumped_at,
            max_words=infer_topic_max_words,
            max_chars=infer_topic_max_chars,
        )
        topic_source = "inferred" if topic and not tokens_from_transcript(transcript) else "transcript"

    mode = infer_mode(transcript)
    return RouteDecision(
        topic=topic,
        mode=mode,
        topic_source=topic_source,
        mode_source="inferred",
    )
