---
paths:
  - "crc_memo/output.py"
  - "crc_memo/summarize.py"
  - "crc_memo/prompts/**"
---
# Report output format

Target shape of the generated reports. Loaded when working on report generation or writing.
Spanish memos get the same structure with Spanish headings (see the es/en table rule in CLAUDE.md).

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
