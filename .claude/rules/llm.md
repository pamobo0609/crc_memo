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
Memos are elderly people retelling a meeting, sent to a WhatsApp **group**. The recipients
are not the speaker and may not have attended.
- `who`: the person named; `""` if nobody is named. `for_recipients: true` when the speaker
  asks whoever receives the audio ("usted", "ustedes", "les pido a todos").
- `due`: as spoken ("el viernes", "antes del 15"); `""` if none. Never compute calendar dates.
- The model often writes placeholders ("no se menciona") or vague dues (*ahorita*) despite
  the prompt → **code** turns them into `null` (`NOT_SAID`, `VAGUE_DUE` in summarize.py).
- Money slang (*cinco rojos* → ₡5.000, *medio palo* → ₡500.000): prompting failed twice →
  `normalize_money()` in code, applied to every text field; quotes stay literal.
- Write values in the memo's language; keys stay English.

## Extraction schema (per chunk) — only what the minuta renders, evidence first
Field order matters: generation is left to right, so `timestamp` + `quote` come **before** the
claim, grounding it instead of inventing a quote afterwards. Length limits (`maxLength`) keep
output short — output length is what makes local extraction slow.
```json
{
  "meeting": [{"group": "Asociación de Vecinos", "when": "ayer", "place": "", "chaired_by": "Don Carlos"}],
  "topics": [{"start": "00:29", "end": "01:25", "title": "Pintura del salón"}],
  "attendees": ["Don Carlos (presidente)", "Doña Rosa (tesorera)"],
  "agreements": [{"timestamp": "00:49", "quote": "la cuota va a ser de cinco rojos", "text": "La cuota sube a cinco rojos"}],
  "commitments": [{"timestamp": "01:59", "quote": "nos mande la lista de los asociados", "what": "Enviar la lista de asociados por WhatsApp", "who": "", "for_recipients": true, "due": "el lunes"}],
  "pending": [{"timestamp": "01:45", "quote": "no sabemos si la muni nos da el permiso", "text": "¿Dará la municipalidad el permiso?"}],
  "observations": [{"timestamp": "00:22", "quote": "estaba bien molesto", "text": "Don Carlos molesto por la baja asistencia"}],
  "tangents": [{"start": "01:10", "end": "01:18", "summary": "La boda de la nieta"}],
  "next_meeting": [{"timestamp": "02:27", "quote": "el sábado 25 a las tres", "day": "el sábado 25", "time": "a las 3 de la tarde", "place": "salón comunal"}]
}
```
`meeting` and `next_meeting` are lists of 0 or 1 items (simpler for constrained decoding than
nullable objects).

## The contract: minutes.json (3b output, 3c input)
Every key maps to something the minuta renders; nothing else travels (quotes stop at 3b).
`source` (sender, memo_date, duration, language) · `meeting` (group, when, place, chaired_by)
· `attendees` · `topics` (id T1…, title, start, end — a topic ends where the next starts) ·
`agreements` / `pending` / `observations` (id A1/P1/O1, topic, text, timestamps) ·
`commitments` (id C1, topic, what, who, for_recipients, due, timestamps) · `next_meeting`
(day, time, place) · `tangents` (start, end, summary). Unknowns are `null`.

## Merge (3b) — the LLM groups, code merges
- The merge prompt lists numbered items per field; the LLM returns `{fact, items}` groups only.
  Writing the **fact before the numbers** fixed wrong groupings that bare `[[1, 4], …]` had.
- Code builds merged items: earliest wording/quote, **all** timestamps, most specific
  owner/due (not "sin asignar"/"sin fecha"). Merging can't change names, amounts or quotes.
- Bad groupings are repaired, never fatal: unknown/repeated numbers dropped, missing ones alone.
- The LLM groups topics too ("Cuotas" = "Cuota de la asociación"); code then assigns each
  item to the topic being discussed at its first timestamp.
- Deterministic parts stay in code: attendee union, tangent ranges, next meeting = last
  mention, observations repeating a tangent or the next meeting are dropped.
- One chunk → no LLM call (extraction already lists each fact once).
- Parked for 3e (all seen only with artificial 60 s chunks; re-check on real 5-min chunks,
  starting with the 27-min real memo):
  - invented "pending" items when the answer lands in the next chunk;
  - an agreement extracted as a commitment without owner;
  - earliest wording can be the weakest ("el costo de los rojos" lost the amount) — consider
    the merge's own `fact` sentence for multi-mention groups;
  - a repeated point becoming its own small topic.
