# crc_memo roadmap

Phase status is tracked in CLAUDE.md. Finish a phase's "done when" before starting the next.

## Phase 0 — Setup ✅
- `brew install ffmpeg ollama uv`, pull 1 model to start.
- `uv init`, add deps, skeleton `cli.py` with `memo --help` working.
- **Done when:** `uv run memo --help` lists stub commands.

## Phase 1 — Ingest ✅
- `memo process [PATH]`; fallback to `osascript -e 'POSIX path of (choose file)'`.
- Convert with ffmpeg to 16kHz mono WAV.
- SHA-256 hash of the original → skip if already processed.
- Store in `data/memos/<id>/` (original + wav).
- **Done when:** picking an `.opus` / `.ogg` / `.m4a` produces a clean `.wav` in its folder;
  running twice skips the second time.

## Phase 2 — Transcription ✅
- mlx-whisper, `large-v3-turbo`, language auto-detect + `--lang` override; save detected language.
- Optional `initial_prompt` from names + curated slang (see `.claude/rules/glossary.md`).
- Save `transcript.txt` (plain) and `segments.json` (with timestamps).
- Show progress with `rich`.
- **Done when:** a 30-min memo transcribes in a few minutes with usable accuracy,
  tested on Spanish memos.

## Phase 3 — Summarization (the core; expect most iteration here)
Memos are mostly elderly people retelling a meeting over WhatsApp, so the output is meeting
minutes (an *acta*): executive summary + detailed report.
- **3a** Chunk `segments.json` (~5 min, split on segment boundaries, 1-segment overlap) and
  extract each chunk to JSON (schema in `.claude/rules/llm.md`): participants, acuerdos, tareas
  (owner = person named, "usted" if the speaker asks the listener, or "sin asignar"),
  pendientes, next meeting, tangents — evidence first (timestamp + quote), in the memo's language.
  Temperature 0 + seed, `think=False`, retry once with the validation error on bad output.
- **3b** Merge + dedupe across chunks (memos repeat themselves a lot); keep every timestamp a
  point was mentioned at.
- **3c** Write the full report, then the exec summary **from the full report**; the LLM returns
  JSON and code renders the markdown (es/en labels, layout in `.claude/rules/output-format.md`).
- **3d** Wire into `memo process` (resumes where it stopped), `memo reprocess ID [--from step]`
  for prompt/model iteration, `--sender` / `--date` overrides (date also read from WhatsApp
  file names like `PTT-20261005-WA0003.opus`), clear errors when Ollama/model are missing.
- **3e** Tune on 3–4 real memos with before/after output.
- Empty glossary step for now — filled in Phase 3.5 only if summaries show it's needed.
- **Done when:** both docs are genuinely useful on 3–4 real memos (mostly Spanish ones).

## Phase 3.5 — Glossary checkpoint (after summaries exist)
Judged by its *effect*, not by match lists: the same memo through `memo reprocess` with and
without glossary entries.
- Run `dcaa.json` matching over real transcripts; review hits (useful / wrong / missing).
- Decide the filter rules (drop Bot./Zool./Usáb., cross-refs, function words; how to handle
  common-word collisions; whether conjugation matching is worth a lemmatizer).
- Note which names/slang Whisper mangled → seed `initial_prompt` and `costa_rica.toml`.
- The dictionary's older/rural vocabulary may suit elderly speakers better than expected.
- **Done when:** the glossary measurably improves summaries — or we decide it isn't needed.

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
- Lemmatized glossary matching (e.g. spaCy `es_core_news_sm`) if Phase 3.5 shows conjugation misses matter.
