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
  truncates input — the #1 cause of bad local summaries. (Demonstrated: at `num_ctx=2048` a
  3.6k-token prompt was cut to 1k tokens and the model confidently answered wrong.)
- **Budget-check before calling**: estimate prompt tokens and refuse if it can't fit
  `num_ctx` minus the output budget. Don't rely on `prompt_eval_count` after the fact.
- Small/mid local models do better with **many simple steps** than one big prompt.
  That's why we chunk → extract → merge instead of "summarize this transcript."
- Use **structured JSON output** (Ollama `format` = Pydantic model's JSON schema). Constrained
  decoding guarantees *syntax*, not truth — validate with the same Pydantic model.
- **Retry once with the error**: at temperature 0 a plain retry repeats the same output, so the
  retry adds the validation error to the conversation.
- **Extraction settings:** temperature 0 + fixed seed (reproducible, so `reprocess` diffs come
  from prompt/model changes), `think=False` (Qwen3 thinks by default: ~40 s extra per call).
- Keep prompts in `crc_memo/prompts/*.md`, never hardcoded in Python. Placeholders are
  `{name}`, filled by plain replacement (not `str.format`, so JSON examples in prompts are safe).
- Model name must be configurable — I'll compare several.

## Meeting context
Memos are elderly people retelling a meeting. The listener ("usted") is not the speaker.
- `owner`: the person named ("Doña Rosa", "el tesorero"), **"usted"** if the speaker asks the
  listener to do it, otherwise **"sin asignar"**. Never guess.
- `due`: as spoken ("el viernes", "antes del 15"); **"sin fecha"** if none or vague
  (*ahorita*). Never compute calendar dates.
- Money slang (*dos rojos* → ₡2.000): the prompt asks, but qwen3:14b ignored it twice —
  normalize **in code** when writing reports (3c); extraction keeps literal quotes.
- Write values in the memo's language; keys stay English.

## Extraction schema (per chunk) — evidence first
Field order matters: generation is left to right, so `timestamp` + `quote` come **before** the
claim, grounding it instead of inventing a quote afterwards.
```json
{
  "topics": ["Pintura del salón comunal"],
  "participants": ["Don Carlos (presidente)", "Doña Rosa (tesorera)"],
  "decisions": [{"timestamp": "03:10", "quote": "quedamos en subir la cuota a cinco mil", "text": "La cuota mensual sube a ₡5.000"}],
  "action_items": [{"timestamp": "05:42", "quote": "a usted le pidieron mandar la lista", "task": "Enviar la lista de asociados por WhatsApp", "owner": "usted", "due": "el lunes"}],
  "open_questions": [{"timestamp": "07:15", "quote": "todavía no sabemos si la muni da el permiso", "text": "¿La municipalidad dará el permiso para el turno?"}],
  "notable": [{"timestamp": "02:05", "quote": "estaba muy molesto", "text": "Don Carlos molesto por la poca asistencia"}],
  "tangents": [{"range": "08:30–10:45", "summary": "Historia sobre la boda de la nieta"}],
  "next_meeting": [{"timestamp": "11:20", "quote": "el sábado 25 a las tres en el salón", "day": "el sábado 25", "time": "a las 3 de la tarde", "place": "salón comunal"}]
}
```
`next_meeting` is a list of 0 or 1 items (simpler for constrained decoding than a nullable object).

## Merge (3b) — the LLM groups, code merges
- The merge prompt lists numbered items per field; the LLM returns `{fact, items}` groups only.
  Writing the **fact before the numbers** fixed wrong groupings that bare `[[1, 4], …]` had.
- Code builds merged items: earliest wording/quote, **all** timestamps, most specific
  owner/due (not "sin asignar"/"sin fecha"). Merging can't change names, amounts or quotes.
- Bad groupings are repaired, never fatal: unknown/repeated numbers dropped, missing ones alone.
- Deterministic parts stay in code: participant/topic union, tangent ranges, next meeting =
  last mention, `notable` items repeating a tangent or the next meeting are dropped.
- One chunk → no LLM call (extraction already lists each fact once).
- Known extraction issue at chunk boundaries (seen with 60 s chunks): invented "unresolved"
  questions when the answer lands in the next chunk. Re-check on real 5-min chunks in 3e.
