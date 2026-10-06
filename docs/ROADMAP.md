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
- **3b** Merge into `minutes.json`, the contract the minuta is rendered from: IDs, topics with
  time spans, items linked to topics, money normalized in code, `null` for unknowns. The LLM only
  groups duplicates; every timestamp a point was mentioned at is kept.
- **3c** Render the minuta breve + completa from `minutes.json`: the LLM writes only prose
  (title, resumen, desarrollo per topic) and code renders everything else (es/en labels,
  layout in `.claude/rules/output-format.md`).
- **3d** Wire into `memo process` (resumes where it stopped), `memo reprocess ID [--from step]`
  for prompt/model iteration, `--sender` / `--date` overrides (date also read from WhatsApp
  file names like `PTT-20261005-WA0003.opus`), clear errors when Ollama/model are missing.
- **3e** Tune on 3–4 real memos with before/after output. Round 1 (27-min spokesperson memo)
  done: owner roles + a focused owner check, line packing, topic/tangent minimums, most
  specific next meeting. Next: more memos (an elderly retelling) rather than more rounds on
  one, to avoid overfitting to one speaker.
- Empty glossary step for now — filled in Phase 3.5 only if summaries show it's needed.
- **Done when:** both docs are genuinely useful on 3–4 real memos (mostly Spanish ones):
  a reviewer can fix the draft quickly using the completa's [mm:ss] — not perfect output.

## Phase 3.5 — Glossary checkpoint (after summaries exist)
Judged by its *effect*, not by match lists: the same memo through `memo reprocess` with and
without glossary entries.
- Run `dcaa.json` matching over real transcripts; review hits (useful / wrong / missing).
- Decide the filter rules (drop Bot./Zool./Usáb., cross-refs, function words; how to handle
  common-word collisions; whether conjugation matching is worth a lemmatizer).
- Note which names/slang Whisper mangled → seed `initial_prompt` and `costa_rica.toml`.
- The dictionary's older/rural vocabulary may suit elderly speakers better than expected.
- **Done when:** the glossary measurably improves summaries — or we decide it isn't needed.

## Phase 4 — Output: Obsidian vault + PDF
Replaces the Google Drive folder / pandoc `--docx` plan. An Obsidian vault is just a folder of
markdown, so there's no lock-in: the tool only writes files. Obsidian is free; its paid Sync is
not needed (rule 1).
- Per memo, a folder `<vault>/Minutas/<YYYY-MM-DD> <group>/` with `Minuta breve.md`,
  `Minuta completa.md`, `Transcripción.md` and a PDF.
- **Obsidian markdown**, rendered from `minutes.json`:
  - **properties** (YAML frontmatter): `fecha`, `grupo`, `relato_de`, `duracion`, `asistentes`,
    `tags: [minuta]` — filter/sort meetings;
  - **wikilinks** for people and groups (`[[Doña Rosa]]`) — backlinks show every meeting
    someone appears in. Names must be normalized (honorific capitalization, one form per
    person) or links split;
  - **task checkboxes** for commitments (`- [ ] … — [[Doña Rosa]] — antes del 15`) — one search
    lists open commitments across all meetings.
- **PDF for the WhatsApp group** (end users, often elderly): large readable text, no timestamps,
  no links. **Typst** via the `typst` Python package (Apache-2.0, self-contained wheel, works
  on Linux CI); the template `crc_memo/templates/minuta.typ` reads `minutes.json` directly, so
  one contract feeds both markdown and PDF.
- Labels and dates localized (es/en table), matching the memo's language.
- **Open decisions** (recommendations in parentheses):
  1. Vault: new vault just for minutas, or a `Minutas/` folder in an existing vault?
  2. PDF: minuta breve only (recommended — it's what the group reads), or both?
  3. Phone access: vault in iCloud Drive works with Obsidian mobile for free — needed?
- **Done when:** a processed memo appears in Obsidian with working properties, backlinks and
  tasks, and its PDF reads well on a phone.

## Phase 5 — History & search (under review)
Obsidian covers most of the original plan: full-text search, backlinks per person, open
commitments via task search. **Proposed:** drop SQLite + FTS5; keep only a simple `memo list`
(read from `data/memos/`) and `memo show`. Revisit if Obsidian falls short.
*(Original plan, kept for reference: SQLite `memos`/`items` tables + FTS5 with
`unicode61 remove_diacritics 2`; `list`, `search`, `show`, `todos`.)*
- **Done when:** decided after Phase 4 is in use.

## Later (only if I want)
- Semantic search (local embeddings, multilingual model e.g. `bge-m3`) — or an Obsidian plugin
  backed by a local model, if Obsidian search falls short.
- Cross-memo tracking ("launch date changed 3 times since August").
- `memo compare --models a,b` — same memo through several models, side by side.
- Watch folder for automatic processing.
- Lemmatized glossary matching (e.g. spaCy `es_core_news_sm`) if Phase 3.5 shows conjugation misses matter.
