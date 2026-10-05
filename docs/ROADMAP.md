# crc_memo roadmap

Phase status is tracked in CLAUDE.md. Finish a phase's "done when" before starting the next.

## Phase 0 — Setup
- `brew install ffmpeg ollama uv`, pull 1 model to start.
- `uv init`, add deps, skeleton `cli.py` with `memo --help` working.
- **Done when:** `uv run memo --help` lists stub commands.

## Phase 1 — Ingest
- `memo process [PATH]`; fallback to `osascript -e 'POSIX path of (choose file)'`.
- Convert with ffmpeg to 16kHz mono WAV.
- SHA-256 hash of the original → skip if already processed.
- Store in `data/memos/<id>/` (original + wav).
- **Done when:** picking an `.opus` / `.ogg` / `.m4a` produces a clean `.wav` in its folder;
  running twice skips the second time.

## Phase 2 — Transcription
- mlx-whisper, `large-v3-turbo`, language auto-detect + `--lang` override; save detected language.
- Optional `initial_prompt` from names + curated slang (see `.claude/rules/glossary.md`).
- Save `transcript.txt` (plain) and `segments.json` (with timestamps).
- Show progress with `rich`.
- **Done when:** a 30-min memo transcribes in a few minutes with usable accuracy,
  tested on Spanish memos.

## Phase 2.5 — Glossary checkpoint
- Run `dcaa.json` matching over 3–4 real transcripts; review the hits (useful / wrong / missing).
- Decide the filter rules (drop Bot./Zool./Usáb., cross-refs, function words; how to handle
  common-word collisions; whether conjugation matching is worth a lemmatizer).
- Note which names/slang Whisper mangled → seed `initial_prompt` and `costa_rica.toml`.
- **Done when:** a curated glossary exists and matching on my memos is mostly useful, not noisy.

## Phase 3 — Summarization (the core; expect most iteration here)
- Chunk by timestamps (~5 min).
- Extract per chunk → schema in `.claude/rules/llm.md`, in the memo's language, with matched glossary entries.
- Merge + dedupe (memos repeat themselves a lot).
- Generate full report, then exec summary from the full report.
- Add `memo reprocess ID` so I can iterate on prompts without re-transcribing.
- **Done when:** both docs are genuinely useful on 3–4 real memos (mostly Spanish ones).

## Phase 4 — Output
- Write `executive-summary.md`, `full-report.md`, `transcript.txt` to
  `<output>/<YYYY-MM-DD> <title>/`. Title comes from the LLM.
- Headings, labels and dates localized (es/en table), matching the memo's language.
- Optional `--docx` via pandoc.
- **Done when:** files appear in the Drive folder and read well on my phone.

## Phase 5 — History & search
- SQLite tables: `memos` (metadata), `items` (action items/decisions/questions from JSON),
  FTS5 virtual table over transcript + reports.
- FTS5 tokenizer `unicode61 remove_diacritics 2` so `reunion` finds `reunión`.
  (No Spanish stemming built in: `decidir` won't match `decidimos` — semantic search covers that later.)
- Implement `list`, `search`, `show`, `todos`.
- **Done when:** I can find "what did he say about X" in seconds across all memos.

## Later (only if I want)
- Semantic search (local embeddings + sqlite-vec). Use a **multilingual** embedding model (e.g. `bge-m3`).
- Cross-memo tracking ("launch date changed 3 times since August").
- `memo compare --models a,b` — same memo through several models, side by side.
- Watch folder for automatic processing.
- Lemmatized glossary matching (e.g. spaCy `es_core_news_sm`) if Phase 2.5 shows conjugation misses matter.
