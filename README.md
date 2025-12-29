# voice2md

Local-first pipeline to turn Android voice notes into **append-only Markdown topic notebooks** in an Obsidian vault, with an optional **Codex “referee”** commentary pass appended after each dump.

## What it does

1. Watches an incoming audio folder (e.g. a Syncthing target like `~/VoiceInbox/`)
2. Waits for files to become “stable” (size/mtime unchanged for `stable_seconds`)
3. Transcribes locally (default: `whisper.cpp`)
4. Routes to a topic notebook (filename topic → inferred topic)
5. Appends:
   - `## Voice Dump — <timestamp>` + transcript
   - `## AI Commentary — <date>` + Codex output (or a placeholder if Codex fails)
6. Archives the audio (configurable) and records the sha256 in a SQLite ledger (idempotent)

Because the notebooks live inside your Obsidian vault (and Syncthing syncs the vault), everything appears back on your phone automatically.

## Repo layout

- `config.yaml` sample config (copy to `~/.config/voice2md/config.yaml`)
- `prompts/referee_prompt.md` referee prompt template (verbatim)
- `src/voice2md/` pipeline implementation + CLI
- `scripts/` dependency + launchd install scripts
- `tests/` minimal unit tests (routing, stable detection, idempotency ledger)

## Setup

### 1) Install Python package (local)

This repo has no required Python deps for the MVP runtime (it shells out to `whisper.cpp` by default).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2) Install `whisper.cpp` (recommended) + ffmpeg

```bash
brew install whisper-cpp ffmpeg
```

Download a `whisper.cpp` ggml model file (e.g. `ggml-medium.bin`) and set its path in your config.

### 3) Configure paths

```bash
mkdir -p ~/.config/voice2md
cp config.yaml ~/.config/voice2md/config.yaml
mkdir -p ~/.config/voice2md/prompts
cp prompts/referee_prompt.md ~/.config/voice2md/prompts/referee_prompt.md
```

Edit `~/.config/voice2md/config.yaml`:

- `paths.inbox_audio_dir` → Syncthing incoming audio folder on Mac
- `paths.obsidian_vault_dir` + `paths.topics_dir` → your Obsidian vault paths
- `paths.archive_audio_dir` → where processed audio files are moved (inside the vault if you want phone access)
- `transcription.whisper_cpp.binary` + `transcription.whisper_cpp.model_path`
- `codex.command` (default works if you have `codex` CLI installed and logged in)

Notes:
- This project reads a small YAML subset (mappings + inline lists like `[a, b]`). Avoid `- dash` lists.
- Relative paths (like `codex.prompt_file: prompts/referee_prompt.md`) resolve relative to the config file directory.

## Usage

Process stable files once and exit:

```bash
voice2md watch --once --config ~/.config/voice2md/config.yaml
```

Run continuously in the foreground:

```bash
voice2md watch --config ~/.config/voice2md/config.yaml
```

Process a single file:

```bash
voice2md process "~/VoiceInbox/2025-12-29 Spin.m4a"
```

Rerun Codex for the latest voice dump in a topic file:

```bash
voice2md rerun-codex ~/ObsidianVault/Topics/Spin.md
```

Run unit tests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Routing rules

Priority order:

1. Filename topic (preferred):
   - Find a `YYYY-MM-DD` anywhere in the filename (excluding extension)
   - Everything after that date becomes the topic (leading spaces/dashes are trimmed)
   - Example: `2025-12-29 Spin notes.m4a` → `Topics/Spin notes.md`
2. If the filename has no topic, infer a topic from the transcript content (keywords / “this is about …” style phrases)

Mode is inferred from the transcript content (roughly: `claims` vs `model-forming` vs `brainstorming`, plus `prep for sharing`).

## launchd (set-and-forget)

Install:

```bash
chmod +x scripts/*.sh
scripts/install_launchd.sh
```

Uninstall:

```bash
scripts/uninstall_launchd.sh
```

The installer writes:
- `~/.config/voice2md/config.yaml` (if missing)
- `~/Library/LaunchAgents/com.voice2md.plist`

## Acceptance test checklist

1. Drop a ~10-minute `.m4a` into `paths.inbox_audio_dir`
2. Run `voice2md watch --once`
3. Confirm a topic file is created/updated under `paths.topics_dir`
4. Confirm it contains:
   - `## Voice Dump — ...` with transcript
   - `## AI Commentary — ...` with Codex output (or a placeholder)
5. Confirm audio is moved under `paths.archive_audio_dir`
6. Run `voice2md watch --once` again → no duplicate entries for the same audio (sha256 idempotency)
7. Open Obsidian (Mac + phone) → the topic notebook appears via Syncthing

## Troubleshooting

- **Nothing processes:** check `~/Library/Logs/voice2md.log` and confirm `paths.inbox_audio_dir` exists.
- **Stuck on partial sync:** raise `processing.stable_seconds` (Syncthing may update file size/mtime while uploading).
- **whisper.cpp fails:** confirm the model file exists and the binary name matches your install. You can change `transcription.whisper_cpp.binary` to an absolute path.
- **Codex fails/offline:** the transcript is still appended; the notebook will include a rerun command. Try `voice2md rerun-codex <topicfile>`.

## Design notes (why it’s built this way)

- **Polling watcher** instead of filesystem events: Syncthing writes/renames/tempfiles; stability windows are simpler and restart-safe.
- **SQLite ledger keyed by sha256:** avoids double-processing even if files are renamed or re-synced.
- **Append-only Markdown:** no rewriting, safe to sync, easy to browse/link in Obsidian.
- **Codex integration via `codex exec --output-last-message`:** captures clean Markdown output while allowing Codex to fail gracefully.
