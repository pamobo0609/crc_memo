# crc_memo — local voice memo summarizer for Costa Rican Spanish (CLI)

## What this is
A command-line tool that takes long voice memos (often 30+ min, rambling, single speaker),
transcribes them locally, and produces:
1. **Executive summary** — one page: TL;DR, acuerdos, tareas (who/what/when), pendientes,
   next meeting, and anything the speaker asks *me* to do.
2. **Full report** — structured by topic, with timestamps, action-item table, and a
   "tangents" section marking what was safe to skip.

**Who the memos come from:** mostly **elderly people retelling a meeting** they attended
(community, association, committee…) as a long WhatsApp audio. I'm the listener, not the
speaker. So the output is **meeting minutes**: owners are the people named in the memo,
"usted" when the speaker asks me for something. Expect slow speech, digressions, repetition
and older/rural Costa Rican vocabulary. Keep the tone respectful; never "correct" the speaker.

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

## Project rules
Repo-wide rules (zero cost unless hard blocked, data stays local, 100% test coverage,
CI green, …) live in CONTRIBUTING.md and apply here too:

@CONTRIBUTING.md

Claude-specific: **commit and push only when I ask.**

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
├── CONTRIBUTING.md     # repo-wide rules
├── .claude/rules/      # topic rules, loaded on demand
├── docs/ROADMAP.md     # phase details
├── .github/workflows/  # CI: tests on ubuntu-latest
├── pyproject.toml
├── crc_memo/
│   ├── cli.py          # Typer commands
│   ├── config.py       # paths, model names, settings
│   ├── ingest.py       # file picker, ffmpeg, hashing
│   ├── transcribe.py   # whisper
│   ├── summarize.py    # chunk → extract → merge → full → exec
│   ├── schemas.py      # JSON schemas for structured extraction
│   ├── output.py       # write reports to the output folder (Phase 4)
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

## Language: Spanish + Costa Rican Spanish
- **Memos are mostly Spanish** (Costa Rican), some English. One language per memo is the norm.
- **Output follows the memo's language**: Spanish memo → Spanish reports.
- **Whisper:** auto-detect by default, `--lang es|en` override (detection only looks at the
  first 30 s and can misfire). Store the detected language in the memo's metadata.
- **Prompts stay in English** with a "Write all output in {language}" instruction — one set
  of prompt files, not one per language. JSON keys stay English; only values are localized.
- **Fixed report text** (headings, labels, dates like `5 oct 2026`) comes from a small
  es/en table in code, not from the LLM, so wording is consistent.
- **Glossary:** `crc_memo/glossary/dcaa.json` (Costa Rican dictionary). Never inject it raw —
  see `.claude/rules/glossary.md` for its limits and how it's used.

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
Full phase details and "done when" criteria: `docs/ROADMAP.md`. **Read the phase's section
before starting it.**
- [x] Phase 0 — Setup
- [x] Phase 1 — Ingest (`memo process`: picker, ffmpeg → 16kHz mono WAV, SHA-256 dedupe)
- [x] Phase 2 — Transcription (mlx-whisper `large-v3-turbo`, `--lang`, segments.json, loop warnings)
  — 27:42 Spanish memo in 1:10 (≈24× real time), 0 loops, usable accuracy
- [ ] Phase 3 — Summarization: meeting minutes (chunk → extract → merge → full → exec, `reprocess`)
- [ ] Phase 3.5 — Glossary checkpoint (judge dcaa.json by its effect on summaries)
- [ ] Phase 4 — Output (markdown to Drive folder, localized headings, optional `--docx`)
- [ ] Phase 5 — History & search (SQLite + FTS5: `list`, `search`, `show`, `todos`)

## Context rules
Topic details load on demand from `.claude/rules/` when matching files are read or edited:
`glossary.md` (Costa Rican glossary), `llm.md` (LLM gotchas + extraction schema),
`output-format.md` (report examples). If you're planning that work before touching those
files, read the rule file directly.

## Prior art (for reference, not dependencies)
Scriberr, Meetily, Applaud — all do local Whisper + Ollama summaries. Worth reading their
code for Whisper/Ollama integration patterns. This project differs by being a CLI,
using chunked structured extraction, and tracking action items across memos.
