from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from voice2md.config import FasterWhisperConfig, TranscriptionConfig, WhisperCppConfig

log = logging.getLogger(__name__)


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriptionResult:
    text: str


class WhisperCppTranscriber:
    def __init__(self, cfg: WhisperCppConfig) -> None:
        self._cfg = cfg

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        if not self._cfg.model_path.exists():
            raise TranscriptionError(f"whisper.cpp model not found: {self._cfg.model_path}")

        with tempfile.TemporaryDirectory(prefix="voice2md_whispercpp_") as tmp:
            input_path = audio_path
            if audio_path.suffix.lower() != ".wav":
                input_path = Path(tmp) / "input.wav"
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(audio_path),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(input_path),
                ]
                log.info("Converting audio via ffmpeg: %s", " ".join(ffmpeg_cmd))
                try:
                    subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
                except FileNotFoundError as e:
                    raise TranscriptionError(
                        "ffmpeg not found (required to transcribe .m4a/.mp3 with whisper.cpp). Install ffmpeg, or use transcription.engine=faster_whisper."
                    ) from e
                except subprocess.CalledProcessError as e:
                    raise TranscriptionError(
                        f"ffmpeg conversion failed (exit {e.returncode}): {e.stderr.strip() or e.stdout.strip()}"
                    ) from e

            out_prefix = Path(tmp) / "transcript"
            cmd = [
                self._cfg.binary,
                "-m",
                str(self._cfg.model_path),
                "-f",
                str(input_path),
                "-t",
                str(self._cfg.threads),
                "-otxt",
                "-of",
                str(out_prefix),
            ]
            if self._cfg.language and self._cfg.language.lower() != "auto":
                cmd += ["-l", self._cfg.language]
            cmd += list(self._cfg.extra_args)

            log.info("Transcribing with whisper.cpp: %s", " ".join(cmd))
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except FileNotFoundError as e:
                raise TranscriptionError(
                    f"whisper.cpp binary not found: {self._cfg.binary}"
                ) from e
            except subprocess.CalledProcessError as e:
                raise TranscriptionError(
                    f"whisper.cpp failed (exit {e.returncode}): {e.stderr.strip() or e.stdout.strip()}"
                ) from e

            txt_path = Path(f"{out_prefix}.txt")
            if not txt_path.exists():
                raise TranscriptionError(
                    "whisper.cpp did not produce expected .txt output; check config.transcription.whisper_cpp.extra_args"
                )

            text = txt_path.read_text(encoding="utf-8").strip()
            return TranscriptionResult(text=text)


class FasterWhisperTranscriber:
    def __init__(self, cfg: FasterWhisperConfig) -> None:
        self._cfg = cfg

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]
        except Exception as e:  # pragma: no cover
            raise TranscriptionError(
                "faster-whisper is not installed. Install it, or switch transcription.engine to whisper_cpp."
            ) from e

        language = None if self._cfg.language.lower() == "auto" else self._cfg.language
        model = WhisperModel(
            self._cfg.model,
            device=self._cfg.device,
            compute_type=self._cfg.compute_type,
        )
        segments, _info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=self._cfg.beam_size,
        )
        text = "".join(s.text for s in segments).strip()
        return TranscriptionResult(text=text)


def build_transcriber(cfg: TranscriptionConfig) -> WhisperCppTranscriber | FasterWhisperTranscriber:
    engine = cfg.engine.strip().lower()
    if engine == "whisper_cpp":
        return WhisperCppTranscriber(cfg.whisper_cpp)
    if engine == "faster_whisper":
        return FasterWhisperTranscriber(cfg.faster_whisper)
    raise TranscriptionError(f"Unknown transcription.engine: {cfg.engine}")
