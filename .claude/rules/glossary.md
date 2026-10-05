---
paths:
  - "crc_memo/glossary/**"
  - "crc_memo/transcribe.py"
  - "crc_memo/summarize.py"
  - "scripts/import_dcaa.py"
---
# Glossary (Costa Rican terms)

Loaded when working on the glossary, transcription or summarization.

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
