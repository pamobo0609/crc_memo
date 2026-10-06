"""Render the minuta as one markdown file, Minuta.md, from minutes.json + prose.json.

Only the prose (title, resumen, desarrollo) comes from the LLM. Everything else is rendered
here: labels and dates come from the es/en table below, so the wording is the same in every
minuta. Sections with nothing in them are left out. Layout: `.claude/rules/output-format.md`.

Minuta.md is built for traceability: YAML frontmatter with provenance, a visible ID on every
item (C1 locally, M12-C1 once published to the vault) and the evidence for each one:
[mm:ss] «the words as said», with ⚠ when code couldn't find the quote in the transcript.
Rendering is deterministic: the same inputs give byte-identical output.
"""

import re
from datetime import date
from pathlib import Path

import yaml

from crc_memo.schemas import Evidence, Minutes, MinutesCommitment, Prose
from crc_memo.summarize import MINUTES_NAME, PROSE_NAME, timestamp_seconds

MINUTA_NAME = "Minuta.md"
BREVE_NAME = "MinutaBreve.md"  # derived from Minuta.md: what the WhatsApp group reads

LABELS = {
    "es": {
        "minuta": "Minuta", "untitled": "Reunión", "due_label": "plazo",
        "generated_from": "Generada desde Minuta.md: corrija allá, no aquí.",
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
        "minuta": "Minutes", "untitled": "Meeting", "due_label": "due",
        "generated_from": "Generated from Minuta.md: correct it there, not here.",
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


def _bold_money(text: str) -> str:
    return COLONES_RE.sub(r"**\g<0>**", text)


def item_id(local_id: str, number: int | None) -> str:
    """"C3" locally; "M12-C3" once the minuta is published as number 12."""
    return f"M{number}-{local_id}" if number else local_id


def commitment_link(cid: str, memo_date: str) -> str:
    """Relative link from Minutas/<YYYY>/<folder>/Minuta.md to Compromisos/<YYYY>/<cid>.md."""
    return f"../../../Compromisos/{memo_date[:4]}/{cid}.md"


def evidence_text(e: Evidence) -> str:
    """[03:45] «the words», ⚠ when code couldn't find them; just [03:45] without a quote
    (minutes merged before quotes were kept)."""
    if not e.quote:
        return f"[{e.timestamp}]"
    return f"[{e.timestamp}] " + ("" if e.verified else "⚠ ") + f"«{e.quote}»"


def _evidence(evidence: list[Evidence]) -> str:
    return " · ".join(map(evidence_text, evidence))


def owner_name(c: MinutesCommitment, m: Minutes, labels: dict) -> str:
    """Who has to do it, as a plain name or role label."""
    if c.owner == "person" and c.who:
        return c.who
    if c.owner == "speaker":  # the speaker's own promise: by name once we know the sender
        return m.source.sender or labels["speaker"]
    if c.owner == "recipients":
        return labels["recipients"]
    return labels["unassigned"]


def _section(title: str, lines: list[str]) -> str | None:
    """A '## title' section, or None when there's nothing to put in it."""
    return f"## {title}\n" + "\n".join(lines) if lines else None


def _header(m: Minutes, labels: dict, recap: bool) -> str | None:
    """Meeting details, then who sent the audio, then attendees. Not a meeting recap: no
    meeting details or attendees (the model invents them); the audio's date goes on line 2."""
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
    if recap and m.attendees:
        lines.append(f"**{labels['attendees']}:** {', '.join(m.attendees)}")
    return "\n".join(line for line in lines if line)


def _recipients(m: Minutes, labels: dict) -> str | None:
    """The highlighted ask, only when the speaker asks the people receiving the audio."""
    asks = [f"> - {c.what}" + (f" — **{c.due}**" if c.due else "")
            for c in m.commitments if c.owner == "recipients"]
    return f"> **{labels['recipients_ask']}:**\n" + "\n".join(asks) if asks else None


def _commitment_line(c: MinutesCommitment, m: Minutes, labels: dict, number: int | None) -> str:
    cid = item_id(c.id, number)
    ref = f"[{cid}]({commitment_link(cid, m.source.memo_date)})" \
        if number and m.source.memo_date else cid
    owner = owner_name(c, m, labels)
    owner = f"**{owner}**" if c.owner == "recipients" else owner
    due = f"{labels['due_label']}: {c.due or labels['no_due']}"
    return f"- **{ref}** · {owner} · {c.what} · {due} — {_evidence(c.evidence)}"


def _next_meeting(m: Minutes, labels: dict) -> str | None:
    parts = [v for v in [m.next_meeting.day, m.next_meeting.time, m.next_meeting.place] if v] \
        if m.next_meeting else []
    text = " · ".join(parts)
    return _section(labels["next_meeting"], [text[:1].upper() + text[1:]] if text else [])


def _topics(m: Minutes, prose: Prose, labels: dict, number: int | None) -> str | None:
    """Each topic: its desarrollo, then the IDs of the acuerdos and compromisos it holds."""
    blocks = []
    for n, topic in enumerate(m.topics, 1):
        refs = " · ".join(
            f"{label}: {', '.join(item_id(i.id, number) for i in items)}"
            for label, items in [(labels["agreements"], [a for a in m.agreements if a.topic == topic.id]),
                                 (labels["commitments"], [c for c in m.commitments if c.topic == topic.id])]
            if items)
        lines = [f"### {n}. {topic.title} [{topic.start}–{topic.end}]",
                 prose.developments.get(topic.id), refs]
        blocks.append("\n".join(line for line in lines if line))
    return f"## {labels['topics']}\n\n" + "\n\n".join(blocks) if blocks else None


def frontmatter(m: Minutes, prose: Prose, number: int | None) -> dict:
    """Machine data for the vault (GitHub shows it as a table). Keys are fixed, in this order."""
    p = m.provenance
    return {
        "numero": number,
        "fecha": yaml_date(m.source.memo_date),
        "titulo": prose.title,
        "grupo": m.meeting.group,
        "relato_de": m.source.sender,
        "es_reunion": prose.meeting_recap,
        "asistentes": m.attendees,
        "duracion": m.source.duration,
        "idioma": m.source.language,
        "memo_id": p and p.memo_id,
        "audio_sha256": p and p.audio_sha256,
        "audio_nombre": p and p.audio_name,
        "whisper": p and p.whisper,
        "llm": p and p.llm,
        "prompts": p and p.prompts,
        "crc_memo": p and p.code,
        "tags": ["minuta"],
    }


def yaml_date(iso: str | None) -> date | str | None:
    """A real date for YAML (written unquoted: Obsidian reads it as a Date property, so it
    sorts and filters); anything that isn't an ISO date stays as it is."""
    try:
        return date.fromisoformat(iso) if iso else iso
    except ValueError:
        return iso


def dump_frontmatter(data: dict) -> str:
    """YAML between --- lines, in the dict's key order (deterministic)."""
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False,
                          width=1000)
    return f"---\n{body}---\n"


def render_minuta(m: Minutes, prose: Prose, number: int | None = None,
                  language: str | None = None) -> str:
    """Minuta.md: frontmatter, then the minuta with an ID and evidence on every item.
    Labels follow the memo's language unless `language` is given (the vault is in Spanish)."""
    labels = labels_for(language or m.source.language)
    title = prose.title or m.meeting.group or labels["untitled"]
    prefix = f"M{number} · " if number else ""
    ev = lambda item: f" — {_evidence(item.evidence)}"  # noqa: E731
    blocks = [
        f"# {prefix}{labels['minuta']} — {title}",
        _header(m, labels, recap=prose.meeting_recap is not False),
        _recipients(m, labels),
        _section(labels["summary"], [prose.summary] if prose.summary else []),
        _topics(m, prose, labels, number),
        _section(labels["agreements"], [f"- **{item_id(a.id, number)}** {_bold_money(a.text)}{ev(a)}"
                                        for a in m.agreements]),
        _section(labels["commitments"], [_commitment_line(c, m, labels, number)
                                         for c in m.commitments]),
        _section(labels["pending"], [f"- **{item_id(p.id, number)}** {p.text}{ev(p)}"
                                     for p in m.pending]),
        _next_meeting(m, labels),
        _section(labels["observations"], [f"- **{item_id(o.id, number)}** {o.text}{ev(o)}"
                                          for o in m.observations]),
        _section(labels["tangents"], [f"- [{t.start}–{t.end}] {t.summary.rstrip('.')} — "
                                      f"{labels['skippable']}" for t in m.tangents]),
    ]
    footer = labels["footer_by"].format(sender=m.source.sender) if m.source.sender \
        else labels["footer"]
    blocks.append(f"---\n*{footer}\n{labels['footer_times']}*")
    body = "\n\n".join(b for b in blocks if b) + "\n"
    return dump_frontmatter(frontmatter(m, prose, number)) + "\n" + body


# The breve drops evidence (" — [03:45] «…»" to the end of the line) and links ([text](url)).
EVIDENCE_RE = re.compile(r" — \[\d{1,2}:\d{2}(?::\d{2})?\].*$")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def split_frontmatter(text: str) -> tuple[dict, str]:
    """(frontmatter, body) of a markdown file; ({}, text) without valid frontmatter."""
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text
    return (data if isinstance(data, dict) else {}), text[match.end():]


def breve_from_minuta(text: str) -> str:
    """MinutaBreve.md, derived from Minuta.md so human corrections there carry over: header,
    the requests to the recipients, resumen, acuerdos, compromisos, pendientes and next
    meeting, with IDs but without quotes, times, links, attendees, topics, observations or
    digressions."""
    front, body = split_frontmatter(text)
    labels = labels_for(front.get("idioma") or "es")
    dropped = {labels["topics"], labels["observations"], labels["tangents"]}
    lines, skipping, footer = [], False, False
    for line in body.split("\n"):
        if line.startswith("## "):
            skipping = line[3:].strip() in dropped
        elif line == "---":
            skipping, footer = False, True
        if skipping or line.startswith(f"**{labels['attendees']}:**"):
            continue
        if footer and line.startswith(labels["footer_times"]):
            lines[-1] += "*"  # the footer's closing * was on the dropped line
            continue
        lines.append(LINK_RE.sub(r"\1", EVIDENCE_RE.sub("", line)))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")
    head = dump_frontmatter({"numero": front.get("numero"), "fecha": front.get("fecha"),
                             "titulo": front.get("titulo"), "tags": ["minuta-breve"]})
    return f"{head}<!-- {labels['generated_from']} -->\n\n{text}\n"


def load(folder: Path) -> tuple[Minutes, Prose]:
    return (Minutes.model_validate_json((folder / MINUTES_NAME).read_text()),
            Prose.model_validate_json((folder / PROSE_NAME).read_text()))


def write(folder: Path) -> list[Path]:
    """Render Minuta.md (unnumbered) into the memo folder. Cheap and deterministic, so it
    always reruns; `memo publish` renders the numbered version into the vault."""
    path = folder / MINUTA_NAME
    text = render_minuta(*load(folder))
    path.write_text(text)
    (folder / BREVE_NAME).write_text(breve_from_minuta(text))
    return [path, folder / BREVE_NAME]
