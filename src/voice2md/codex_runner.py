from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from voice2md.config import CodexConfig

log = logging.getLogger(__name__)


class CodexError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodexResult:
    markdown: str


def _load_prompt_template(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as e:
        raise CodexError(f"Prompt file not found: {path}") from e


def build_referee_input(
    *,
    prompt_template_path: Path,
    today: str,
    notebook_context_markdown: str,
    latest_voice_dump_markdown: str,
) -> str:
    template = _load_prompt_template(prompt_template_path)
    parts: list[str] = [
        f"Today is {today}.",
        "",
        template,
    ]
    if notebook_context_markdown.strip():
        parts += [
            "",
            "---",
            "## Context From Notebook (most recent sections)",
            notebook_context_markdown.strip(),
        ]
    parts += [
        "",
        "---",
        "## Latest Voice Dump (critique this)",
        latest_voice_dump_markdown.strip(),
        "",
    ]
    return "\n".join(parts)


def _ensure_output_last_message(cmd: list[str], output_path: Path) -> list[str]:
    if any(part in {"-o", "--output-last-message"} for part in cmd):
        return cmd

    # Inject before prompt argument (`-`) if present.
    try:
        idx = cmd.index("-")
    except ValueError:
        cmd = cmd + ["-"]
        idx = len(cmd) - 1

    return cmd[:idx] + ["--output-last-message", str(output_path)] + cmd[idx:]


def _inject_model(cmd: list[str], model: str) -> list[str]:
    model = model.strip()
    if not model:
        return cmd
    if any(part in {"-m", "--model"} for part in cmd):
        return cmd
    try:
        idx = cmd.index("-")
    except ValueError:
        idx = len(cmd)
    return cmd[:idx] + ["--model", model] + cmd[idx:]


def _inject_reasoning_effort(cmd: list[str], reasoning_effort: str) -> list[str]:
    reasoning_effort = reasoning_effort.strip()
    if not reasoning_effort:
        return cmd

    # If the user already supplied a config override for this, respect it.
    for part in cmd:
        if "model_reasoning_effort" in part:
            return cmd

    try:
        idx = cmd.index("-")
    except ValueError:
        idx = len(cmd)

    # Codex CLI parses the value as TOML, so we must quote the string.
    return cmd[:idx] + ["-c", f'model_reasoning_effort="{reasoning_effort}"'] + cmd[idx:]


def run_codex(cfg: CodexConfig, *, stdin_prompt: str) -> CodexResult:
    if not cfg.enabled:
        raise CodexError("Codex is disabled in config")
    if not cfg.command:
        raise CodexError("codex.command is empty")

    base_cmd = list(cfg.command)
    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")

    with tempfile.TemporaryDirectory(prefix="voice2md_codex_") as tmp:
        out_path = Path(tmp) / "codex_last_message.txt"
        cmd = _ensure_output_last_message(base_cmd, out_path)
        cmd = _inject_model(cmd, cfg.model)
        cmd = _inject_reasoning_effort(cmd, cfg.model_reasoning_effort)

        log.info("Running Codex: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                input=stdin_prompt,
                text=True,
                capture_output=True,
                timeout=cfg.timeout_seconds,
                env=env,
                check=True,
            )
        except FileNotFoundError as e:
            raise CodexError(f"Codex command not found: {cmd[0]}") from e
        except subprocess.TimeoutExpired as e:
            if out_path.exists():
                text = out_path.read_text(encoding="utf-8").strip()
                if text:
                    log.warning(
                        "Codex timed out after %ss but produced an output file; using partial output",
                        cfg.timeout_seconds,
                    )
                    return CodexResult(markdown=text)
            raise CodexError(
                f"Codex timed out after {cfg.timeout_seconds}s "
                f"(increase codex.timeout_seconds in config.yaml)"
            ) from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            stdout = (e.stdout or "").strip()
            detail = stderr or stdout or f"exit {e.returncode}"
            raise CodexError(f"Codex failed: {detail}") from e

        if out_path.exists():
            text = out_path.read_text(encoding="utf-8").strip()
        else:
            text = ""
        if not text:
            raise CodexError("Codex produced no output (empty last message)")
        return CodexResult(markdown=text)
