---
paths:
  - "crc_memo/output.py"
  - "crc_memo/summarize.py"
  - "crc_memo/prompts/**"
---
# Output: the minuta (breve + completa)

Rendered from `minutes.json` (contract in `.claude/rules/llm.md`). The LLM writes only prose
(title, resumen, desarrollo per topic); code renders everything else. Labels and dates come
from the es/en table in code. Sections with nothing in them are omitted. It's built from a
retelling, so it says so — never present it as an official acta.

Decisions (with the user): desvíos and observaciones only in the completa; [mm:ss] timestamps
only in the completa; the recipients line appears only when the speaker asks the recipients.

### Minuta breve (Spanish memo)
```markdown
# Minuta — Reunión de la Asociación de Vecinos
**Reunión:** ayer, según el audio del 5 oct 2026 · **Lugar:** salón comunal · **Presidió:** Don Carlos
**Relato de:** Marta · audio de 27 min

> **Piden a quienes reciben el audio:** enviar la lista de asociados por WhatsApp — **el lunes**

## Resumen
La cuota sube a ₡5.000 desde noviembre para pintar el salón. El turno de diciembre depende
de un permiso municipal que aún no está confirmado.

## Acuerdos
1. Pintar el salón comunal antes de diciembre.
2. La cuota mensual sube a **₡5.000** desde noviembre.

## Compromisos
| Responsable | Compromiso | Plazo |
|---|---|---|
| Doña Rosa | Cotizar la pintura del salón | antes del 15 |
| Jorge | Hablar con la municipalidad (permiso y alumbrado) | sin fecha |
| **Quienes reciben el audio** | Enviar la lista de asociados por WhatsApp | el lunes |

## Pendientes
- ¿Dará la municipalidad el permiso para el turno?

## Próxima reunión
Sábado 25 · 3 de la tarde · Salón comunal
```

### Minuta completa (Spanish memo)
```markdown
# Minuta completa — Reunión de la Asociación de Vecinos
(same header) · **Asistentes:** Don Carlos (presidente), Doña Rosa (tesorera), Jorge, Doña Lupe

## Temas tratados
### 1. Pintura del salón comunal [00:29–01:25]
Desarrollo: 2–5 sentences on what was discussed.
Acuerdos: 1, 2 · Compromisos: Doña Rosa

### 2. Turno de diciembre [01:25–02:06]
…

## Acuerdos            (numbered, with [mm:ss] — every mention: [00:49, 02:13])
## Compromisos         (table with a Fuente [mm:ss] column)
## Pendientes
## Próxima reunión
## Observaciones       (e.g. Don Carlos molesto por la baja asistencia [00:22])
## Desvíos del audio   ([01:10–01:18] La boda de la nieta — se puede saltar)
---
*Minuta elaborada automáticamente a partir del relato de Marta; no es un acta oficial.
Los minutos [mm:ss] indican dónde verificarlo en el audio.*
```
