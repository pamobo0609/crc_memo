---
paths:
  - "crc_memo/summarize.py"
  - "crc_memo/schemas.py"
  - "crc_memo/prompts/**"
---
# LLM pipeline: gotchas and extraction schema

Loaded when working on summarization, schemas or prompts.

## Critical LLM gotchas
- **Always set `num_ctx`** (≥ 16384) on Ollama calls. The default is small and silently
  truncates input — the #1 cause of bad local summaries.
- Small/mid local models do better with **many simple steps** than one big prompt.
  That's why we chunk → extract → merge instead of "summarize this transcript."
- Use **structured JSON output** (Ollama `format` with a JSON schema) for extraction.
  Validate it; retry once on parse failure.
- Keep prompts in `crc_memo/prompts/*.md`, never hardcoded in Python.
- Model name must be configurable — I'll compare several.


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
