from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


def _strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i]
    return line


_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\d*\.\d+)$")


def _parse_scalar(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None

    if _INT_RE.match(value):
        try:
            return int(value)
        except ValueError:
            pass

    if _FLOAT_RE.match(value):
        try:
            return float(value)
        except ValueError:
            pass

    if value.startswith(("'", '"', "[", "{")):
        try:
            return ast.literal_eval(value)
        except Exception:
            return value

    return value


def _load_yaml_subset(path: Path) -> dict[str, Any]:
    """
    Minimal YAML subset loader:
      - mappings via indentation (2 spaces recommended)
      - scalars: strings, ints, floats, bools, null
      - inline lists/dicts: [..] / {..} via Python literal syntax

    Not supported:
      - dash lists
      - multi-line strings
    """
    if not path.exists():
        raise ConfigError(f"Config not found: {path}")

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(0, root)]
    expecting_indent: int | None = None

    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = _strip_inline_comment(raw_line).rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            raise ConfigError(f"{path}:{lineno}: indentation must use spaces (multiple of 2)")

        content = line.strip()
        if ":" not in content:
            raise ConfigError(f"{path}:{lineno}: expected 'key: value' mapping")

        if expecting_indent is not None and indent > expecting_indent:
            raise ConfigError(
                f"{path}:{lineno}: unexpected indentation (expected {expecting_indent} spaces)"
            )

        while stack and indent < stack[-1][0]:
            stack.pop()

        if not stack:
            raise ConfigError(f"{path}:{lineno}: invalid indentation structure")

        current_indent, current_map = stack[-1]
        if indent != current_indent:
            raise ConfigError(
                f"{path}:{lineno}: indentation mismatch (expected {current_indent} spaces)"
            )

        key, raw_value = content.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()

        if not key:
            raise ConfigError(f"{path}:{lineno}: empty key")

        if raw_value == "":
            new_map: dict[str, Any] = {}
            current_map[key] = new_map
            stack.append((indent + 2, new_map))
            expecting_indent = None
            continue

        current_map[key] = _parse_scalar(raw_value)
        expecting_indent = None

    return root


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def _expand_path(value: str | None) -> Path | None:
    if value is None:
        return None
    return Path(os.path.expandvars(value)).expanduser()


@dataclass(frozen=True)
class PathsConfig:
    inbox_audio_dir: Path
    obsidian_vault_dir: Path
    topics_dir: Path
    archive_audio_dir: Path
    log_file: Path


@dataclass(frozen=True)
class AudioConfig:
    archive_copy_enabled: bool
    delete_original_after_archive: bool


@dataclass(frozen=True)
class StateConfig:
    backend: str
    path: Path


@dataclass(frozen=True)
class ProcessingConfig:
    allowed_extensions: tuple[str, ...]
    stable_seconds: int
    poll_interval_seconds: int
    in_progress_ttl_seconds: int
    archive_subdir_format: str


@dataclass(frozen=True)
class WhisperCppConfig:
    binary: str
    model_path: Path
    language: str
    threads: int
    extra_args: tuple[str, ...]


@dataclass(frozen=True)
class FasterWhisperConfig:
    model: str
    device: str
    compute_type: str
    language: str
    beam_size: int


@dataclass(frozen=True)
class TranscriptionConfig:
    engine: str
    whisper_cpp: WhisperCppConfig
    faster_whisper: FasterWhisperConfig


@dataclass(frozen=True)
class RoutingConfig:
    infer_topic_max_words: int
    infer_topic_max_chars: int


@dataclass(frozen=True)
class CodexConfig:
    enabled: bool
    command: tuple[str, ...]
    model: str
    timeout_seconds: int
    prompt_file: Path
    context_voice_dumps: int
    context_ai_commentaries: int
    context_max_chars: int


@dataclass(frozen=True)
class AppConfig:
    paths: PathsConfig
    state: StateConfig
    audio: AudioConfig
    processing: ProcessingConfig
    transcription: TranscriptionConfig
    routing: RoutingConfig
    codex: CodexConfig
    config_path: Path


DEFAULT_CONFIG: dict[str, Any] = {
    "paths": {
        "inbox_audio_dir": "~/VoiceInbox",
        "obsidian_vault_dir": "~/ObsidianVault",
        "topics_dir": "~/ObsidianVault/Topics",
        "archive_audio_dir": "~/ObsidianVault/_attachments/audio",
        "log_file": "~/Library/Logs/voice2md.log",
    },
    "state": {"backend": "json", "path": "~/.config/voice2md/state.json"},
    "audio": {"archive_copy_enabled": False, "delete_original_after_archive": False},
    "processing": {
        "allowed_extensions": [".m4a", ".mp3", ".wav", ".aac"],
        "stable_seconds": 10,
        "poll_interval_seconds": 5,
        "in_progress_ttl_seconds": 3600,
        "archive_subdir_format": "%Y/%m",
    },
    "transcription": {
        "engine": "whisper_cpp",
        "whisper_cpp": {
            "binary": "whisper-cli",
            "model_path": "~/Models/whisper.cpp/ggml-medium.bin",
            "language": "auto",
            "threads": 6,
            "extra_args": [],
        },
        "faster_whisper": {
            "model": "medium",
            "device": "auto",
            "compute_type": "int8",
            "language": "auto",
            "beam_size": 5,
        },
    },
    "routing": {"infer_topic_max_words": 6, "infer_topic_max_chars": 80},
    "codex": {
        "enabled": True,
        "command": ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-"],
        "model": "",
        "timeout_seconds": 180,
        "prompt_file": "prompts/referee_prompt.md",
        "context_voice_dumps": 3,
        "context_ai_commentaries": 1,
        "context_max_chars": 20000,
    },
}


def default_config_path() -> Path:
    env = os.environ.get("VOICE2MD_CONFIG")
    if env:
        return Path(env).expanduser()

    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.exists():
        return cwd_config

    return Path("~/.config/voice2md/config.yaml").expanduser()


def load_config(path: Path | None = None) -> AppConfig:
    config_path = (path or default_config_path()).expanduser()
    data = _load_yaml_subset(config_path)
    merged = _deep_merge(DEFAULT_CONFIG, data)

    user_paths = data.get("paths", {}) if isinstance(data.get("paths", {}), dict) else {}
    user_state = data.get("state") if isinstance(data.get("state"), dict) else None

    paths = merged.get("paths", {})
    state = merged.get("state", {})
    audio = merged.get("audio", {})
    processing = merged.get("processing", {})
    transcription = merged.get("transcription", {})
    routing = merged.get("routing", {})
    codex = merged.get("codex", {})

    prompt_path = codex.get("prompt_file", DEFAULT_CONFIG["codex"]["prompt_file"])
    prompt_path = Path(prompt_path) if isinstance(prompt_path, str) else Path(str(prompt_path))
    if not prompt_path.is_absolute():
        prompt_path = (config_path.parent / prompt_path).resolve()

    whisper_cpp = transcription.get("whisper_cpp", {})
    faster_whisper = transcription.get("faster_whisper", {})

    # Backward compatibility: older configs used `paths.state_db_path` for sqlite, and had no `state:` section.
    legacy_state_db_path = user_paths.get("state_db_path")
    if user_state is None and legacy_state_db_path:
        state_backend = "sqlite"
        state_path_raw = legacy_state_db_path
    else:
        state_backend = str(state.get("backend", DEFAULT_CONFIG["state"]["backend"])).strip().lower()
        state_path_raw = state.get("path", DEFAULT_CONFIG["state"]["path"])

    return AppConfig(
        paths=PathsConfig(
            inbox_audio_dir=_expand_path(str(paths["inbox_audio_dir"])) or Path(),
            obsidian_vault_dir=_expand_path(str(paths["obsidian_vault_dir"])) or Path(),
            topics_dir=_expand_path(str(paths["topics_dir"])) or Path(),
            archive_audio_dir=_expand_path(str(paths["archive_audio_dir"])) or Path(),
            log_file=_expand_path(str(paths["log_file"])) or Path(),
        ),
        state=StateConfig(
            backend=state_backend,
            path=_expand_path(str(state_path_raw)) or Path(),
        ),
        audio=AudioConfig(
            archive_copy_enabled=bool(audio.get("archive_copy_enabled", False)),
            delete_original_after_archive=bool(audio.get("delete_original_after_archive", False)),
        ),
        processing=ProcessingConfig(
            allowed_extensions=tuple(processing.get("allowed_extensions", [])),
            stable_seconds=int(processing.get("stable_seconds", 10)),
            poll_interval_seconds=int(processing.get("poll_interval_seconds", 5)),
            in_progress_ttl_seconds=int(processing.get("in_progress_ttl_seconds", 3600)),
            archive_subdir_format=str(processing.get("archive_subdir_format", "%Y/%m")),
        ),
        transcription=TranscriptionConfig(
            engine=str(transcription.get("engine", "whisper_cpp")),
            whisper_cpp=WhisperCppConfig(
                binary=str(whisper_cpp.get("binary", "whisper-cli")),
                model_path=_expand_path(str(whisper_cpp.get("model_path", ""))) or Path(),
                language=str(whisper_cpp.get("language", "auto")),
                threads=int(whisper_cpp.get("threads", 6)),
                extra_args=tuple(whisper_cpp.get("extra_args", [])),
            ),
            faster_whisper=FasterWhisperConfig(
                model=str(faster_whisper.get("model", "medium")),
                device=str(faster_whisper.get("device", "auto")),
                compute_type=str(faster_whisper.get("compute_type", "int8")),
                language=str(faster_whisper.get("language", "auto")),
                beam_size=int(faster_whisper.get("beam_size", 5)),
            ),
        ),
        routing=RoutingConfig(
            infer_topic_max_words=int(routing.get("infer_topic_max_words", 6)),
            infer_topic_max_chars=int(routing.get("infer_topic_max_chars", 80)),
        ),
        codex=CodexConfig(
            enabled=bool(codex.get("enabled", True)),
            command=tuple(codex.get("command", [])),
            model=str(codex.get("model", "")),
            timeout_seconds=int(codex.get("timeout_seconds", 180)),
            prompt_file=prompt_path,
            context_voice_dumps=int(codex.get("context_voice_dumps", 3)),
            context_ai_commentaries=int(codex.get("context_ai_commentaries", 1)),
            context_max_chars=int(codex.get("context_max_chars", 20000)),
        ),
        config_path=config_path,
    )
