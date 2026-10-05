# crc_memo — local voice memo summarizer for Costa Rican Spanish (CLI)

## What this is
A command-line tool that takes long voice memos (often 30+ min, rambling, single speaker),
transcribes them locally, and produces:
1. **Executive summary** — one page: TL;DR, my action items, decisions, open questions.
2. **Full report** — structured by topic, with timestamps, action-item table, and a
   "tangents" section marking what was safe to skip.

It also keeps a **history** of every processed memo and offers **search** across them.

## Hard constraints
- **$0 to run.** No paid APIs, no API keys, no cloud services. Everything local and open source.
- **Local-only data.** Audio, transcripts, and outputs never leave the machine
  (except the output folder, which is synced by Google Drive for desktop — not by this tool).
- **CLI only.** No GUI, no web server. The only "UI" is the native macOS file picker via `osascript`.
- **Target machine:** macOS. Assume Apple Silicon unless told otherwise (affects Whisper choice).

## How to work with me
- This is a **learning project**. I have mobile + backend experience but I'm new to the
  Python AI tooling. Explain *why* when you introduce a library, pattern, or model setting.
- Work in **small, testable steps**. Finish one phase's "done when" before starting the next.
- Before big changes, propose the plan briefly and wait for my OK.
- Prefer simple, readable code over clever abstractions. No frameworks beyond what's listed.
- When tuning prompts (Phase 3), show me before/after output so I can judge quality.

## Stack
| Concern | Tool | Notes |
|---|---|---|
| Project / deps | `uv` | `uv add`, `uv run` |
| CLI | `typer` + `rich` | |
| Audio conversion | `ffmpeg` (brew) | → 16kHz mono WAV |
| Transcription | `mlx-whisper` | `large-v3-turbo`. Use `faster-whisper` if not Apple Silicon |
| LLM | Ollama (brew) via HTTP API or `ollama` Python package | Local models only |
| Storage + search | SQLite + FTS5 (stdlib `sqlite3`) | Single file |
| Optional later | `sqlite-vec` + multilingual local embedding model (e.g. `bge-m3`; Spanish memos) | Semantic search |
| Optional export | `pandoc` (brew) | `--docx` flag |

## Project layout
```
crc_memo/
├── CLAUDE.md
├── pyproject.toml
├── crc_memo/
│   ├── cli.py          # Typer commands
│   ├── config.py       # paths, model names, settings
│   ├── ingest.py       # file picker, ffmpeg, hashing
│   ├── transcribe.py   # whisper
│   ├── summarize.py    # chunk → extract → merge → full → exec
│   ├── schemas.py      # JSON schemas for structured extraction
│   ├── db.py           # sqlite + FTS5
│   ├── prompts/        # one .md file per prompt, loaded at runtime
│   └── glossary/       # dcaa.json — Costa Rican Spanish dictionary (generated once)
├── scripts/            # one-off tools (import_dcaa.py)
└── tests/
```

Data lives in `data/` inside the project (`memo.db`, `memos/<id>/`; gitignored). Output folder is configurable,
default: a Google Drive synced folder, e.g. `~/Google Drive/Memos/`.

## Pipeline
```
audio file → ffmpeg (16kHz mono wav) → whisper (timestamped transcript)
  → chunk (~5 min segments)
  → extract per chunk (JSON via Ollama `format` schema)
  → merge + dedupe extractions
  → full report (from merged data)
  → exec summary (from full report, NOT from raw transcript)
  → write markdown to output folder + index in SQLite
```

### Critical LLM gotchas
- **Always set `num_ctx`** (≥ 16384) on Ollama calls. The default is small and silently
  truncates input — the #1 cause of bad local summaries.
- Small/mid local models do better with **many simple steps** than one big prompt.
  That's why we chunk → extract → merge instead of "summarize this transcript."
- Use **structured JSON output** (Ollama `format` with a JSON schema) for extraction.
  Validate it; retry once on parse failure.
- Keep prompts in `crc_memo/prompts/*.md`, never hardcoded in Python.
- Model name must be configurable — I'll compare several.

## Language: Spanish + Costa Rican Spanish
- **Memos are mostly Spanish** (Costa Rican), some English. One language per memo is the norm.
- **Output follows the memo's language**: Spanish memo → Spanish reports.
- **Whisper:** auto-detect by default, `--lang es|en` override (detection only looks at the
  first 30 s and can misfire). Store the detected language in the memo's metadata.
- **Prompts stay in English** with a "Write all output in {language}" instruction — one set
  of prompt files, not one per language. JSON keys stay English; only values are localized.
- **Fixed report text** (headings, labels, dates like `5 oct 2026`) comes from a small
  es/en table in code, not from the LLM, so wording is consistent.

### Glossary (Costa Rican terms)
- `crc_memo/glossary/dcaa.json` — Agüero's *Diccionario de costarriqueñismos*, OCR-imported once by
  `scripts/import_dcaa.py` (12,909 entries, 2,440 phrases). Tracked in git; don't rerun casually.
- **Known limits — don't inject it raw:**
  - Common words collide: *obra* → "excremento humano", *viernes* → "viejo", *carro* → a shrub.
    Function words (*a, con, que*) match grammar notes. Unfiltered matching misleads the LLM.
  - Headwords are base forms; speech is conjugated (*jalar* vs *jalé*, *rojo* vs *rojos*).
  - It's older/rural usage. Modern slang is largely missing (*mae, birra, chante, jama,
    despiche, sele, ocupar* = necesitar).
  - Residual OCR noise in rare headwords (`telegraf"l8da`).
- **How it's used:**
  - **LLM (Phase 3):** per chunk, inject only entries that appear in that chunk
    (accent/case-insensitive), after filtering. Never the whole dictionary.
  - **Whisper (Phase 2):** `initial_prompt` holds ~220 tokens — use a short natural Spanish
    sentence with names + the slang Whisper actually mangles in my memos, not dictionary dumps.
- **Planned additions:**
  - `crc_memo/glossary/costa_rica.toml` — hand-curated modern slang (tracked).
  - `data/glossary.toml` — personal names of people/clients/projects (gitignored).
- **Policy in reports:** transcript stays verbatim; summaries use the standard meaning
  (*brete* → trabajo); money slang normalized (*dos rojos* → ₡2.000); vague timing like
  *ahorita* → due date *sin fecha*, never an invented date.

## Extraction schema (per chunk)
```json
{
  "topics": ["website relaunch"],
  "action_items": [{"task": "Send mockups to Laura", "owner": "me", "due": "Friday", "timestamp": "08:15"}],
  "decisions": ["Blog cut from v1"],
  "open_questions": ["Is hosting budget approved?"],
  "notable": ["Client unhappy with load times"],
  "tangents": [{"summary": "Story about old agency project", "range": "21:00–25:30"}],
  "timestamp_range": "05:00–10:00"
}
```

## CLI commands (target)
```
memo process [PATH]        # no PATH → native macOS file picker
memo list                  # date, title, duration, # open action items
memo search "query"        # FTS hits with timestamps
memo show ID [--exec|--full|--transcript]
memo todos                 # open action items across all memos
memo reprocess ID          # rerun summarization (e.g. after prompt/model change)
```

---

## Roadmap

### Phase 0 — Setup
- `brew install ffmpeg ollama uv`, pull 1 model to start.
- `uv init`, add deps, skeleton `cli.py` with `memo --help` working.
- **Done when:** `uv run memo --help` lists stub commands.

### Phase 1 — Ingest
- `memo process [PATH]`; fallback to `osascript -e 'POSIX path of (choose file)'`.
- Convert with ffmpeg to 16kHz mono WAV.
- SHA-256 hash of the original → skip if already processed.
- Store in `data/memos/<id>/` (original + wav).
- **Done when:** picking an `.opus` / `.ogg` / `.m4a` produces a clean `.wav` in its folder;
  running twice skips the second time.

### Phase 2 — Transcription
- mlx-whisper, `large-v3-turbo`, language auto-detect + `--lang` override; save detected language.
- Optional `initial_prompt` from names + curated slang (see Glossary).
- Save `transcript.txt` (plain) and `segments.json` (with timestamps).
- Show progress with `rich`.
- **Done when:** a 30-min memo transcribes in a few minutes with usable accuracy,
  tested on Spanish memos.

### Phase 2.5 — Glossary checkpoint
- Run `dcaa.json` matching over 3–4 real transcripts; review the hits (useful / wrong / missing).
- Decide the filter rules (drop Bot./Zool./Usáb., cross-refs, function words; how to handle
  common-word collisions; whether conjugation matching is worth a lemmatizer).
- Note which names/slang Whisper mangled → seed `initial_prompt` and `costa_rica.toml`.
- **Done when:** a curated glossary exists and matching on my memos is mostly useful, not noisy.

### Phase 3 — Summarization (the core; expect most iteration here)
- Chunk by timestamps (~5 min).
- Extract per chunk → schema above, in the memo's language, with matched glossary entries.
- Merge + dedupe (memos repeat themselves a lot).
- Generate full report, then exec summary from the full report.
- Add `memo reprocess ID` so I can iterate on prompts without re-transcribing.
- **Done when:** both docs are genuinely useful on 3–4 real memos (mostly Spanish ones).

### Phase 4 — Output
- Write `executive-summary.md`, `full-report.md`, `transcript.txt` to
  `<output>/<YYYY-MM-DD> <title>/`. Title comes from the LLM.
- Headings, labels and dates localized (es/en table), matching the memo's language.
- Optional `--docx` via pandoc.
- **Done when:** files appear in the Drive folder and read well on my phone.

### Phase 5 — History & search
- SQLite tables: `memos` (metadata), `items` (action items/decisions/questions from JSON),
  FTS5 virtual table over transcript + reports.
- FTS5 tokenizer `unicode61 remove_diacritics 2` so `reunion` finds `reunión`.
  (No Spanish stemming built in: `decidir` won't match `decidimos` — semantic search covers that later.)
- Implement `list`, `search`, `show`, `todos`.
- **Done when:** I can find "what did he say about X" in seconds across all memos.

### Later (only if I want)
- Semantic search (local embeddings + sqlite-vec). Use a **multilingual** embedding model (e.g. `bge-m3`).
- Cross-memo tracking ("launch date changed 3 times since August").
- `memo compare --models a,b` — same memo through several models, side by side.
- Watch folder for automatic processing.
- Lemmatized glossary matching (e.g. spaCy `es_core_news_sm`) if Phase 2.5 shows conjugation misses matter.

---

## Output format examples

### executive-summary.md
```markdown
# Website Relaunch Update — Oct 5, 2026
**Duration:** 31 min · **Sender:** Marco · **Processed:** Oct 5, 14:22

## TL;DR
Relaunch moves to Nov 15 (was Nov 1) because the client wants a new checkout flow.
Blog is cut from v1. You owe Laura updated mockups by Friday.

## What you need to do
- [ ] Send updated homepage + checkout mockups to Laura — **Fri Oct 9**
- [ ] Confirm whether you can cover QA week of Nov 9

## Decisions made
- Launch date moved to **Nov 15**
- Blog removed from v1, revisit in January

## Open questions
- Hosting budget increase not yet approved
- No owner for content migration

## Worth knowing
Client is frustrated with current load times — performance will likely be the main
judgment criterion at launch.
```

### full-report.md
```markdown
# Website Relaunch Update — Full Report
Oct 5, 2026 · 31 min · Marco

## 1. Timeline change [00:30–06:10]
Client requested a redesigned checkout after seeing a competitor's site. Adds ~2 weeks.
New launch date: Nov 15. Repeated at [18:45] and [27:10].

## 2. Scope cuts [06:10–11:40]
- Blog removed from v1
- Newsletter signup stays, simplified to email-only

## 3. Hosting and performance [11:40–19:30]
...

## Tangents (safe to skip)
- [21:00–25:30] Story about a previous agency project; no action items.

## Action items
| Task | Owner | Due | Source |
|---|---|---|---|
| Updated mockups to Laura | Me | Fri Oct 9 | [08:15] |
| Confirm QA availability | Me | — | [29:40] |
| Check hosting budget | Marco | — | [15:20] |

## Open questions
...
```

## Prior art (for reference, not dependencies)
Scriberr, Meetily, Applaud — all do local Whisper + Ollama summaries. Worth reading their
code for Whisper/Ollama integration patterns. This project differs by being a CLI,
using chunked structured extraction, and tracking action items across memos.
