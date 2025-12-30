from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from voice2md.codex_runner import CodexError, build_referee_input, run_codex
from voice2md.config import AppConfig, load_config
from voice2md.logging_setup import setup_logging
from voice2md.markdown import (
    append_block,
    extract_context,
    extract_latest_sections,
)
from voice2md.pipeline import process_audio_file
from voice2md.state import open_state_store
from voice2md.watcher import Watcher

log = logging.getLogger(__name__)


def _load(cfg_path: str | None, *, verbose: bool) -> AppConfig:
    cfg = load_config(Path(cfg_path).expanduser() if cfg_path else None)
    setup_logging(cfg.paths.log_file, verbose=verbose)
    return cfg


def cmd_watch(args: argparse.Namespace) -> int:
    cfg = _load(args.config, verbose=args.verbose)
    watcher = Watcher(cfg)
    try:
        if args.once:
            watcher.run_once()
            return 0
        watcher.run_forever()
        return 0
    finally:
        watcher.close()


def cmd_process(args: argparse.Namespace) -> int:
    cfg = _load(args.config, verbose=args.verbose)
    state = open_state_store(path=cfg.state.path, backend=cfg.state.backend)
    try:
        outcome = process_audio_file(cfg, audio_path=Path(args.file), state=state, force=args.force)
        if outcome:
            print(outcome.topic_file)
        return 0
    finally:
        state.close()


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _load(args.config, verbose=args.verbose)
    state = open_state_store(path=cfg.state.path, backend=cfg.state.backend)
    try:
        stats = state.stats()
        print(f"processed={stats['processed']} failed={stats['failed']} in_progress={stats['in_progress']}")
        return 0
    finally:
        state.close()


def cmd_rerun_codex(args: argparse.Namespace) -> int:
    cfg = _load(args.config, verbose=args.verbose)
    topic_file = Path(args.topic_file).expanduser().resolve()

    latest = extract_latest_sections(topic_file)
    if not latest.latest_voice_dump:
        print("No voice dumps found.")
        return 2

    if not args.force and latest.last_section_kind == "AI Commentary":
        # Allow rerun if placeholder is present.
        if latest.latest_ai_commentary and "(Codex unavailable;" in latest.latest_ai_commentary:
            pass
        else:
            print("Latest voice dump already has AI commentary. Use --force to append another.")
            return 0

    context = extract_context(
        topic_file,
        voice_dumps=cfg.codex.context_voice_dumps,
        ai_commentaries=cfg.codex.context_ai_commentaries,
        max_chars=cfg.codex.context_max_chars,
        skip_latest_voice_dump=True,
    )
    today = datetime.now().strftime("%Y-%m-%d")
    stdin_prompt = build_referee_input(
        prompt_template_path=cfg.codex.prompt_file,
        today=today,
        notebook_context_markdown=context.markdown,
        latest_voice_dump_markdown=latest.latest_voice_dump,
    )
    try:
        result = run_codex(cfg.codex, stdin_prompt=stdin_prompt)
        commentary = result.markdown.strip()
        if not commentary.lstrip().startswith("## AI Commentary —"):
            commentary = f"## AI Commentary — {today}\n\n{commentary}"
        append_block(topic_file, commentary, include_separator=True)
        return 0
    except CodexError as e:
        print(f"Codex failed: {e}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="voice2md")
    p.add_argument("--config", help="Path to config.yaml (default: auto)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("watch", help="Watch inbox folder and process new audio")
    w.add_argument("--once", action="store_true", help="Process stable files once and exit")
    w.set_defaults(func=cmd_watch)

    pr = sub.add_parser("process", help="Process a single audio file")
    pr.add_argument("file", help="Path to audio file")
    pr.add_argument("--force", action="store_true", help="Reprocess even if already processed")
    pr.set_defaults(func=cmd_process)

    st = sub.add_parser("status", help="Show ledger counts")
    st.set_defaults(func=cmd_status)

    rc = sub.add_parser("rerun-codex", help="Append Codex commentary for the latest voice dump")
    rc.add_argument("topic_file", help="Path to a topic markdown file")
    rc.add_argument("--force", action="store_true", help="Append even if latest already has commentary")
    rc.set_defaults(func=cmd_rerun_codex)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
