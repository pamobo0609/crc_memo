---
paths:
  - "crc_memo/output.py"
  - "crc_memo/vault.py"
  - "crc_memo/summarize.py"
  - "crc_memo/prompts/**"
---
# Output: Minuta.md (one file) and the vault

Rendered from `minutes.json` + `prose.json` (contract in `.claude/rules/llm.md`). The LLM writes
only prose (title, resumen, desarrollo per topic); code renders everything else. Labels and
dates come from the es/en table in `output.py`. Sections with nothing in them are omitted.
It's built from a retelling, so it says so — never present it as an official acta.

- **One file, `Minuta.md`** (the old breve/completa pair is gone). Locally in
  `data/memos/<id>/` with plain IDs (`C1`); in the vault numbered (`M12-C1`). The breve/PDF
  for the group is a view derived from it (Phase 4d).
- **Frontmatter** (fixed key order, YAML): numero, fecha, titulo, grupo, relato_de,
  es_reunion, asistentes, duracion, idioma, then provenance (memo_id, audio_sha256,
  audio_nombre, whisper, llm, prompts, crc_memo) and tags.
- **Every item has a visible ID and its evidence**: `[mm:ss] «quote»`, ⚠ before the quote
  when code couldn't find it in the transcript; just `[mm:ss]` for minutes merged before
  quotes were kept.
- **Commitment owners**: the name (`person`); the sender's name, or "Quien envía el audio"
  (`speaker`); **Quienes reciben el audio** (`recipients`, also in the callout at the top);
  "sin asignar" (`nobody`).
- Not a meeting recap (`es_reunion: false`): no Reunión/Lugar/Presidió/Asistentes.

```markdown
---
numero: 12
fecha: '2026-10-05'
titulo: Reunión de la Asociación de Vecinos
...
---

# M12 · Minuta — Reunión de la Asociación de Vecinos

**Reunión:** ayer, según el audio del 5 oct 2026 · **Lugar:** salón comunal · **Presidió:** Don Carlos
**Relato de:** Marta · audio de 28 min
**Asistentes:** Don Carlos (presidente), Doña Rosa (tesorera)

> **Piden a quienes reciben el audio:**
> - Enviar la lista de asociados por WhatsApp — **el lunes**

## Resumen
## Temas tratados
### 1. Pintura del salón comunal [00:29–01:25]
Desarrollo…
Acuerdos: M12-A1, M12-A2 · Compromisos: M12-C1

## Acuerdos
- **M12-A1** La cuota sube a **₡5.000** desde noviembre. — [00:49] «cinco rojos al mes» · [02:13] ⚠ «…»
## Compromisos
- **[M12-C1](../../../Compromisos/2026/M12-C1.md)** · Doña Rosa · Cotizar la pintura · plazo: antes del 15 — [01:03] «…»
## Pendientes / Próxima reunión / Observaciones / Desvíos del audio
---
*Minuta elaborada automáticamente…; no es un acta oficial.
Los minutos [mm:ss] indican dónde verificarlo en el audio.*
```

## Vault (`vault.py`)
- Paths: `Minutas/<YYYY>/M12-<date>/{Minuta,Transcripcion}.md`, `Compromisos/<YYYY>/M12-C3.md`.
  ASCII PascalCase file names, no spaces (`file_name()`); text inside keeps accents.
- Numbers: next = highest ever + 1, never reused; republish (same audio_sha256) keeps it.
- Human-owned after publish: Minuta.md (republish needs `--force` if edited), commitment
  notes (never overwritten: they hold status + Seguimiento).
- `memo publish ID` commits and pushes (`--no-push`); deterministic commit message.
- `MinutaBreve.md` (generated, never edit): derived from `Minuta.md` by `breve_from_minuta()`
  — header, recipients callout, resumen, acuerdos, compromisos, pendientes, next meeting; IDs
  kept; quotes, times, links, attendees, topics, observations, digressions dropped.
- Names: `Propietarios.md` (one row per person) + `Externos.md`, column «También dicen»
  (`;`-separated) → `name_map()`; `apply_names()` replaces whole words, case-insensitive,
  longest first, never inside «quotes» or in Transcripcion.md. Applied on publish and by
  `memo vault update`, which skips files with uncommitted edits and commits only what it changed.
