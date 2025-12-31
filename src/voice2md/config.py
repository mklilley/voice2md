from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config not found: {path}")

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as e:
        raise ConfigError(
            "PyYAML is required to parse config.yaml. Install it with: pip install pyyaml"
        ) from e

    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e

    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ConfigError(f"Invalid config: expected a top-level mapping in {path}")
    return parsed


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
    model_reasoning_effort: str
    web_search_enabled: bool
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
        "model_reasoning_effort": "",
        "web_search_enabled": False,
        "timeout_seconds": 600,
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
    data = _load_yaml(config_path)
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
            model_reasoning_effort=str(codex.get("model_reasoning_effort", "")),
            web_search_enabled=bool(codex.get("web_search_enabled", False)),
            timeout_seconds=int(codex.get("timeout_seconds", 180)),
            prompt_file=prompt_path,
            context_voice_dumps=int(codex.get("context_voice_dumps", 3)),
            context_ai_commentaries=int(codex.get("context_ai_commentaries", 1)),
            context_max_chars=int(codex.get("context_max_chars", 20000)),
        ),
        config_path=config_path,
    )
