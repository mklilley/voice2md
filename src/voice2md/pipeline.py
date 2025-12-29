from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from voice2md.archive import ensure_archived_copy, finalize_archived_move, plan_archive_path
from voice2md.codex_runner import CodexError, build_referee_input, run_codex
from voice2md.config import AppConfig
from voice2md.markdown import (
    extract_context,
    format_voice_dump_section,
    notebook_contains_sha256,
    sanitize_topic,
    topic_file_path,
    append_block,
    ensure_topic_file,
)
from voice2md.router import decide_route
from voice2md.state import StateStore
from voice2md.transcribe import TranscriptionError, build_transcriber
from voice2md.util import path_rel_to, sha256_file

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessOutcome:
    audio_path: Path
    sha256: str
    topic_file: Path
    archived_audio: Path | None
    codex_status: str | None


def _infer_dump_time(audio_path: Path) -> datetime:
    try:
        st = audio_path.stat()
        return datetime.fromtimestamp(st.st_mtime)
    except FileNotFoundError:
        return datetime.now()


def process_audio_file(
    cfg: AppConfig,
    *,
    audio_path: Path,
    state: StateStore,
    force: bool = False,
) -> ProcessOutcome | None:
    audio_path = audio_path.expanduser().resolve()
    if not audio_path.exists():
        log.warning("File vanished before processing: %s", audio_path)
        return None

    sha = sha256_file(audio_path)
    if state.is_processed(sha) and not force:
        log.info("Already processed (sha256): %s", audio_path.name)
        return None

    if not state.allow_retry_in_progress(sha, cfg.processing.in_progress_ttl_seconds) and not force:
        log.info("In-progress elsewhere (skipping for now): %s", audio_path.name)
        return None

    state.mark_in_progress(sha, audio_path, force=True)
    dumped_at = _infer_dump_time(audio_path)

    transcriber = build_transcriber(cfg.transcription)
    try:
        transcript = transcriber.transcribe(audio_path).text
    except TranscriptionError as e:
        state.mark_failed(sha, str(e))
        raise

    decision = decide_route(
        audio_path=audio_path,
        transcript=transcript,
        dumped_at=dumped_at,
        infer_topic_max_words=cfg.routing.infer_topic_max_words,
        infer_topic_max_chars=cfg.routing.infer_topic_max_chars,
    )
    topic_title = sanitize_topic(decision.topic, fallback="Untitled")
    topic_file = topic_file_path(cfg.paths.topics_dir, topic_title)
    created = ensure_topic_file(topic_file, topic_title=topic_title)

    archived_audio: Path | None = None
    planned_archive = plan_archive_path(
        source_path=audio_path,
        archive_root=cfg.paths.archive_audio_dir,
        subdir_format=cfg.processing.archive_subdir_format,
        now=dumped_at,
    )
    source_audio_str = path_rel_to(cfg.paths.obsidian_vault_dir, planned_archive)
    try:
        archived_audio = ensure_archived_copy(source_path=audio_path, dest_path=planned_archive)
    except Exception as e:
        log.warning("Archive copy failed; continuing without archived link: %s (%s)", audio_path, e)
        archived_audio = None
        source_audio_str = audio_path.name

    if notebook_contains_sha256(topic_file, sha) and not force:
        log.info("Notebook already contains sha256 marker; skipping append: %s", audio_path.name)
        if archived_audio is not None:
            try:
                finalize_archived_move(source_path=audio_path)
            except Exception:
                log.exception("Failed to remove original audio after detecting existing notebook entry")
        state.mark_processed(
            sha,
            archive_path=archived_audio,
            topic_file=topic_file,
            codex_status="skipped",
        )
        return ProcessOutcome(
            audio_path=audio_path,
            sha256=sha,
            topic_file=topic_file,
            archived_audio=archived_audio,
            codex_status="skipped",
        )

    voice_dump_md = format_voice_dump_section(
        dumped_at=dumped_at,
        source_audio=source_audio_str,
        mode=decision.mode,
        transcript=transcript,
        audio_sha256=sha,
    )
    append_block(topic_file, voice_dump_md, include_separator=not created)

    codex_status: str | None = None
    today = datetime.now().strftime("%Y-%m-%d")
    if cfg.codex.enabled:
        try:
            context = extract_context(
                topic_file,
                voice_dumps=cfg.codex.context_voice_dumps,
                ai_commentaries=cfg.codex.context_ai_commentaries,
                max_chars=cfg.codex.context_max_chars,
                skip_latest_voice_dump=True,
            )
            stdin_prompt = build_referee_input(
                prompt_template_path=cfg.codex.prompt_file,
                today=today,
                notebook_context_markdown=context.markdown,
                latest_voice_dump_markdown=voice_dump_md,
            )
            result = run_codex(cfg.codex, stdin_prompt=stdin_prompt)
            commentary = result.markdown.strip()
            if not commentary.lstrip().startswith("## AI Commentary —"):
                commentary = f"## AI Commentary — {today}\n\n{commentary}"
            append_block(topic_file, commentary, include_separator=True)
            codex_status = "ok"
        except CodexError as e:
            rerun_cmd = f'voice2md rerun-codex "{topic_file}"'
            placeholder = (
                f"## AI Commentary — {today}\n\n"
                f"(Codex unavailable; rerun: `{rerun_cmd}`)\n\n"
                f"Error: {e}\n"
            )
            append_block(topic_file, placeholder, include_separator=True)
            codex_status = "unavailable"
    else:
        codex_status = "disabled"

    if archived_audio is not None:
        try:
            finalize_archived_move(source_path=audio_path)
        except Exception:
            log.exception("Failed to remove original audio after processing")

    state.mark_processed(
        sha,
        archive_path=archived_audio,
        topic_file=topic_file,
        codex_status=codex_status,
    )
    return ProcessOutcome(
        audio_path=audio_path,
        sha256=sha,
        topic_file=topic_file,
        archived_audio=archived_audio,
        codex_status=codex_status,
    )
