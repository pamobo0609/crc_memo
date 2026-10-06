"""Render the minuta (breve + completa) as markdown from minutes.json + prose.json.

Only the prose (title, resumen, desarrollo) comes from the LLM. Everything else is rendered
here: labels and dates come from the es/en table below, so the wording is the same in every
minuta. Sections with nothing in them are left out. Layout: `.claude/rules/output-format.md`.
Phase 4 adds the Obsidian touches (properties, [[links]], task checkboxes) and the PDF.
"""

import re
from datetime import date
from pathlib import Path

from crc_memo.schemas import Minutes, MinutesCommitment, Prose
from crc_memo.summarize import MINUTES_NAME, PROSE_NAME, timestamp_seconds

BREVE_NAME = "minuta_breve.md"
COMPLETA_NAME = "minuta_completa.md"

LABELS = {
    "es": {
        "minuta": "Minuta", "minuta_completa": "Minuta completa", "untitled": "Reunión",
        "meeting": "Reunión", "per_audio": "según el audio del {date}", "place": "Lugar",
        "chaired_by": "Presidió", "told_by": "Relato de", "audio": "audio de {duration}",
        "audio_dated": "audio de {duration} del {date}",
        "attendees": "Asistentes",
        "recipients_ask": "Piden a quienes reciben el audio",
        "recipients": "Quienes reciben el audio", "speaker": "Quien envía el audio",
        "summary": "Resumen", "topics": "Temas tratados", "agreements": "Acuerdos",
        "commitments": "Compromisos", "who": "Responsable", "what": "Compromiso", "due": "Plazo",
        "source": "Fuente", "unassigned": "sin asignar", "no_due": "sin fecha",
        "pending": "Pendientes", "next_meeting": "Próxima reunión",
        "observations": "Observaciones", "tangents": "Desvíos del audio",
        "skippable": "se puede saltar",
        "footer_by": "Minuta elaborada automáticamente a partir del relato de {sender}; "
                     "no es un acta oficial.",
        "footer": "Minuta elaborada automáticamente a partir de un audio; no es un acta oficial.",
        "footer_times": "Los minutos [mm:ss] indican dónde verificarlo en el audio.",
        "months": "ene feb mar abr may jun jul ago sep oct nov dic".split(),
    },
    "en": {
        "minuta": "Minutes", "minuta_completa": "Full minutes", "untitled": "Meeting",
        "meeting": "Meeting", "per_audio": "per the audio of {date}", "place": "Place",
        "chaired_by": "Chaired by", "told_by": "Told by", "audio": "{duration} audio",
        "audio_dated": "{duration} audio of {date}",
        "attendees": "Attendees",
        "recipients_ask": "The speaker asks everyone receiving the audio",
        "recipients": "Everyone receiving the audio", "speaker": "The sender",
        "summary": "Summary", "topics": "Topics discussed", "agreements": "Agreements",
        "commitments": "Commitments", "who": "Who", "what": "Commitment", "due": "Due",
        "source": "Source", "unassigned": "unassigned", "no_due": "no date",
        "pending": "Pending", "next_meeting": "Next meeting",
        "observations": "Observations", "tangents": "Digressions in the audio",
        "skippable": "safe to skip",
        "footer_by": "Minutes written automatically from {sender}'s account; "
                     "not official minutes.",
        "footer": "Minutes written automatically from a voice memo; not official minutes.",
        "footer_times": "The [mm:ss] times show where to check it in the audio.",
        "months": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
    },
}
# Amounts are already "₡5.000" (normalized in 3b); acuerdos show them in bold.
COLONES_RE = re.compile(r"₡\d+(?:\.\d{3})*")


def labels_for(language: str) -> dict:
    """Labels in the memo's language; English for languages without a table."""
    return LABELS.get(language, LABELS["en"])


def format_date(iso: str, labels: dict) -> str:
    """'2026-10-05' -> '5 oct 2026'. Anything that isn't an ISO date is shown as is."""
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {labels['months'][d.month - 1]} {d.year}"


def format_duration(duration: str) -> str:
    """'27:42' -> '28 min', '1:05:10' -> '1 h 05 min'. Never '0 min'."""
    minutes = max(1, round(timestamp_seconds(duration) / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02} min" if hours else f"{minutes} min"


def _cell(text: str) -> str:
    """Safe inside a markdown table cell."""
    return text.replace("|", "\\|")


def _bold_money(text: str) -> str:
    return COLONES_RE.sub(r"**\g<0>**", text)


def _times(timestamps: list[str]) -> str:
    return f"[{', '.join(timestamps)}]"


def _owner(c: MinutesCommitment, m: Minutes, labels: dict, bold: bool = True) -> str:
    if c.owner == "person" and c.who:
        return c.who
    if c.owner == "speaker":  # the speaker's own promise: by name once we know the sender
        return m.source.sender or labels["speaker"]
    if c.owner == "recipients":
        return f"**{labels['recipients']}**" if bold else labels["recipients"]
    return labels["unassigned"]


def _section(title: str, lines: list[str]) -> str | None:
    """A '## title' section, or None when there's nothing to put in it."""
    return f"## {title}\n" + "\n".join(lines) if lines else None


def _header(m: Minutes, labels: dict, full: bool, recap: bool) -> str | None:
    """Meeting details, then who sent the audio. Not a meeting recap: no meeting details or
    attendees (the model invents them), and the audio's date goes on the second line."""
    duration = format_duration(m.source.duration)
    date_ = m.source.memo_date and format_date(m.source.memo_date, labels)
    meeting = ""
    if recap:
        when = ", ".join(v for v in [m.meeting.when,
                                     date_ and labels["per_audio"].format(date=date_)] if v)
        meeting = " · ".join(f"**{labels[key]}:** {value}" for key, value in
                             [("meeting", when), ("place", m.meeting.place),
                              ("chaired_by", m.meeting.chaired_by)] if value)
        audio = labels["audio"].format(duration=duration)
    else:
        audio = (labels["audio_dated"].format(duration=duration, date=date_) if date_
                 else labels["audio"].format(duration=duration))
    told_by = m.source.sender and f"**{labels['told_by']}:** {m.source.sender}"
    lines = [meeting, " · ".join(v for v in [told_by, audio] if v)]
    if full and recap and m.attendees:
        lines.append(f"**{labels['attendees']}:** {', '.join(m.attendees)}")
    return "\n".join(line for line in lines if line)


def _recipients(m: Minutes, labels: dict) -> str | None:
    """The highlighted ask, only when the speaker asks the people receiving the audio."""
    asks = [f"> - {c.what}" + (f" — **{c.due}**" if c.due else "")
            for c in m.commitments if c.owner == "recipients"]
    return f"> **{labels['recipients_ask']}:**\n" + "\n".join(asks) if asks else None


def _commitments(m: Minutes, labels: dict, full: bool) -> str | None:
    if not m.commitments:
        return None
    columns = [labels["who"], labels["what"], labels["due"]] + ([labels["source"]] if full else [])
    rows = [f"| {' | '.join(columns)} |", "|" + "---|" * len(columns)]
    for c in m.commitments:
        cells = [_owner(c, m, labels), c.what, c.due or labels["no_due"]]
        cells += [_times(c.timestamps)] if full else []
        rows.append(f"| {' | '.join(_cell(x) for x in cells)} |")
    return f"## {labels['commitments']}\n" + "\n".join(rows)


def _next_meeting(m: Minutes, labels: dict) -> str | None:
    parts = [v for v in [m.next_meeting.day, m.next_meeting.time, m.next_meeting.place] if v] \
        if m.next_meeting else []
    text = " · ".join(parts)
    return _section(labels["next_meeting"], [text[:1].upper() + text[1:]] if text else [])


def _topics(m: Minutes, prose: Prose, labels: dict) -> str | None:
    """Each topic: its desarrollo, then which acuerdos (by number) and compromisos it holds."""
    blocks = []
    for n, topic in enumerate(m.topics, 1):
        agreements = [str(i) for i, a in enumerate(m.agreements, 1) if a.topic == topic.id]
        owners = list(dict.fromkeys(_owner(c, m, labels, bold=False)
                                    for c in m.commitments if c.topic == topic.id))
        refs = " · ".join(f"{label}: {', '.join(values)}" for label, values in
                          [(labels["agreements"], agreements), (labels["commitments"], owners)]
                          if values)
        lines = [f"### {n}. {topic.title} [{topic.start}–{topic.end}]",
                 prose.developments.get(topic.id), refs]
        blocks.append("\n".join(line for line in lines if line))
    return f"## {labels['topics']}\n\n" + "\n\n".join(blocks) if blocks else None


def render(m: Minutes, prose: Prose, full: bool = False) -> str:
    """The minuta breve (`full=False`) or the minuta completa (`full=True`), as markdown."""
    labels = labels_for(m.source.language)
    title = prose.title or m.meeting.group or labels["untitled"]
    times = (lambda timestamps: f" {_times(timestamps)}") if full else (lambda timestamps: "")

    blocks = [
        f"# {labels['minuta_completa' if full else 'minuta']} — {title}",
        _header(m, labels, full, recap=prose.meeting_recap is not False),
        _recipients(m, labels),
    ]
    if full:
        blocks.append(_topics(m, prose, labels))
    else:
        blocks.append(_section(labels["summary"], [prose.summary] if prose.summary else []))
    blocks += [
        _section(labels["agreements"], [f"{n}. {_bold_money(a.text)}{times(a.timestamps)}"
                                        for n, a in enumerate(m.agreements, 1)]),
        _commitments(m, labels, full),
        _section(labels["pending"], [f"- {p.text}{times(p.timestamps)}" for p in m.pending]),
        _next_meeting(m, labels),
    ]
    if full:
        blocks += [
            _section(labels["observations"],
                     [f"- {o.text}{times(o.timestamps)}" for o in m.observations]),
            _section(labels["tangents"], [f"- [{t.start}–{t.end}] {t.summary.rstrip('.')} — {labels['skippable']}"
                                          for t in m.tangents]),
        ]
    footer = labels["footer_by"].format(sender=m.source.sender) if m.source.sender \
        else labels["footer"]
    if full:
        footer += "\n" + labels["footer_times"]
    blocks.append(f"---\n*{footer}*")
    return "\n\n".join(b for b in blocks if b) + "\n"


def write(folder: Path) -> list[Path]:
    """Render both minutas into the memo folder. Cheap and deterministic, so it always reruns."""
    minutes = Minutes.model_validate_json((folder / MINUTES_NAME).read_text())
    prose = Prose.model_validate_json((folder / PROSE_NAME).read_text())
    paths = []
    for name, full in [(BREVE_NAME, False), (COMPLETA_NAME, True)]:
        path = folder / name
        path.write_text(render(minutes, prose, full))
        paths.append(path)
    return paths
