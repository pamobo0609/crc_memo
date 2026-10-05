---
paths:
  - "crc_memo/output.py"
  - "crc_memo/summarize.py"
  - "crc_memo/prompts/**"
---
# Report output format

Target shape of the generated reports: **meeting minutes** retold by an (often elderly) speaker.
Loaded when working on report generation or writing. Headings, labels and dates come from the
es/en table in code; the LLM writes only the prose and items. English memos get the same
structure with English labels. Sections with nothing in them are omitted.

### executive-summary.md (Spanish memo)
```markdown
# Reunión de la Asociación de Vecinos — 5 oct 2026
**Duración:** 27 min · **Envía:** Doña Marta · **Procesado:** 5 oct 2026, 14:22

## En resumen
La cuota mensual sube a ₡5.000 desde noviembre para pintar el salón comunal. Doña Rosa
cotiza la pintura antes del 15. Falta saber si la municipalidad da el permiso para el turno.

## Le piden a usted
- [ ] Enviar la lista de asociados por WhatsApp — **el lunes** [05:42]

## Acuerdos
- La cuota mensual sube a **₡5.000** desde noviembre [03:10, repetido 12:40]
- El turno se hace en diciembre si hay permiso [09:05]

## Tareas
| Quién | Qué | Cuándo |
|---|---|---|
| Doña Rosa | Cotizar la pintura del salón | antes del 15 |
| Jorge | Hablar con la municipalidad sobre el alumbrado | sin fecha |

## Pendientes
- ¿La municipalidad dará el permiso para el turno?

## Próxima reunión
Sábado 25 a las 3 p. m., salón comunal
```

### full-report.md (Spanish memo)
```markdown
# Reunión de la Asociación de Vecinos — Informe completo
5 oct 2026 · 27 min · Doña Marta

**Participantes:** Don Carlos (presidente), Doña Rosa (tesorera), Jorge

## 1. Cuota y pintura del salón [00:30–06:10]
Don Carlos propuso subir la cuota para pintar el salón... Se acordó ₡5.000 desde noviembre.
Se repitió en [12:40].

## 2. Turno de diciembre [06:10–11:40]
...

## Tareas
| Quién | Qué | Cuándo | Fuente |
|---|---|---|---|
| Usted | Enviar la lista de asociados por WhatsApp | el lunes | [05:42] |
| Doña Rosa | Cotizar la pintura del salón | antes del 15 | [04:15] |

## Pendientes
...

## Desvíos (se pueden saltar)
- [08:30–10:45] Historia sobre la boda de la nieta; sin acuerdos ni tareas.
```
