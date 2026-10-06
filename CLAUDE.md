# crc_memo — local voice memo summarizer for Costa Rican Spanish (CLI)

## What this is
A command-line tool that takes long voice memos (often 30+ min, rambling, single speaker),
transcribes them locally, and produces:
1. **Minuta breve** (executive) — resumen, acuerdos, compromisos (who/what/by when),
   pendientes, próxima reunión, and a highlighted line when the speaker asks the recipients.
2. **Minuta completa** (detailed) — temas tratados with development and [mm:ss] ranges,
   asistentes, observaciones, and "desvíos" marking what was safe to skip.
   Both are rendered from `minutes.json` (the contract; see `.claude/rules/output-format.md`).

**Who the memos come from:** mostly **elderly people retelling a meeting** they attended
(community, association, committee…) as a long WhatsApp audio **sent to a group** — or the
group's **spokesperson reporting back** to the people they represent (says "ustedes" in every
sentence; makes promises of their own). I'm one of the recipients, not the speaker.
So the output is a **minuta**: each commitment has an `owner` — a person named, the speaker
(their own promise), the recipients (only on an explicit ask: "traigan", "les pido que
firmen"), or nobody. Expect slow speech, digressions, repetition and older/rural Costa Rican
vocabulary. Keep the tone respectful; never "correct" the speaker.

**The tool drafts, a human reviews.** The minuta does the heavy lifting; someone reads it
before it goes to the group. The minuta completa (with [mm:ss] to check against the audio)
is the reference. So "good enough" means: saves the reviewer most of the work, and its
mistakes are easy to spot and verify — not perfect.

Outputs go to a **vault**: a private GitHub repo (free tier) of plain markdown, laid out so it
reads well on GitHub and in Obsidian (no Obsidian app needed). It's built for traceability:
human IDs (`M12`, `M12-C3`), quotes + [mm:ss] on every item, provenance, git history of every
correction. Plus a **PDF** to share with the group. Layout and rules: `docs/ROADMAP.md` Phase 4.

## Hard constraints
- **$0 to run.** No paid APIs, no API keys, no cloud services. Everything local and open source.
- **Local-only data, except the vault.** Audio and working files (`data/`) never leave the
  machine. Published minutas + transcripts go to my **private** GitHub vault repo:
  `memo publish` commits and pushes there (`--no-push` to keep it local). Nothing else is ever
  sent anywhere, and the audio is never published (only its SHA-256).
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
| Output | Obsidian vault (markdown) + PDF via `typst` (Python package) | Phase 4 |
| Search / tracking | Obsidian (search, properties, aliases) + generated vault indexes | Phase 5 resolved: no SQLite |
| Optional later | Multilingual local embedding model (e.g. `bge-m3`; Spanish memos) | Semantic search |

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
│   ├── output.py       # render minutes.json → Obsidian markdown + PDF (Phase 4)
│   ├── templates/      # minuta.typ (Typst PDF template, Phase 4)
│   ├── prompts/        # one .md file per prompt, loaded at runtime
│   └── glossary/       # dcaa.json — Costa Rican Spanish dictionary (generated once)
├── scripts/            # one-off tools (import_dcaa.py)
└── tests/
```

Data lives in `data/` inside the project (`memos/<id>/`; gitignored). Published output goes to
the vault, a local clone of the private repo at `$CRC_MEMO_VAULT` (Phase 4).

## Pipeline
```
audio file → ffmpeg (16kHz mono wav) → whisper (timestamped transcript)
  → chunk (~5 min segments)
  → extract per chunk (JSON via Ollama `format` schema)
  → merge + dedupe extractions
  → full report (from merged data)
  → exec summary (from full report, NOT from raw transcript)
  → render Obsidian markdown + PDF into the vault
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

## CLI commands
```
memo process [PATH] [--sender NAME] [--date YYYY-MM-DD]   # no PATH → macOS file picker
memo reprocess ID [--from extract|merge|write|render] [--sender] [--date]
                           # rerun summarization; old outputs kept in <memo>/history/
memo publish ID [--no-push] [--force]   # number it (M12) and publish to the vault
memo vault init PATH | update [--no-push] | check
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
- [x] Phase 4 — Output: traceable vault (private GitHub repo: Minuta.md, IDs M12-C3, evidence, `memo publish`, names, indexes, `vault check`) + PDF for the group — first minuta (M1) published, reviewed and shared
- [x] Phase 5 — History & search: resolved — Obsidian + generated indexes cover it (no SQLite)

## Context rules
Topic details load on demand from `.claude/rules/` when matching files are read or edited:
`glossary.md` (Costa Rican glossary), `llm.md` (LLM gotchas + extraction schema),
`output-format.md` (report examples). If you're planning that work before touching those
files, read the rule file directly.

## Prior art (for reference, not dependencies)
Scriberr, Meetily, Applaud — all do local Whisper + Ollama summaries. Worth reading their
code for Whisper/Ollama integration patterns. This project differs by being a CLI,
using chunked structured extraction, and tracking action items across memos.
