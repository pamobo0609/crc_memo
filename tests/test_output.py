from datetime import date
import json

import pytest
import yaml

from crc_memo import output
from crc_memo.schemas import (Evidence, Provenance, Entry, Meeting, Minutes, MinutesCommitment, MinutesNextMeeting,
                              Prose, Source, Tangent, Topic)


def ev(*timestamps):
    """Evidence for made-up items: a placeholder quote at each time."""
    return [Evidence(timestamp=ts, quote=f"cita {ts}") for ts in timestamps]


def minutes(**changes) -> Minutes:
    """The example minuta from .claude/rules/output-format.md (made-up data)."""
    base = Minutes(
        source=Source(sender="Marta", memo_date="2026-10-05", duration="27:42", language="es"),
        meeting=Meeting(group="Asociación de Vecinos", when="ayer", place="salón comunal",
                        chaired_by="Don Carlos"),
        attendees=["Don Carlos (presidente)", "Doña Rosa (tesorera)", "Jorge"],
        topics=[Topic(id="T1", title="Pintura del salón comunal", start="00:29", end="01:25"),
                Topic(id="T2", title="Turno de diciembre", start="01:25", end="02:06")],
        agreements=[Entry(id="A1", topic="T1", text="Pintar el salón comunal antes de diciembre.",
                          evidence=ev("00:40")),
                    Entry(id="A2", topic="T1", text="La cuota mensual sube a ₡5.000 desde noviembre.",
                          evidence=ev("00:49", "02:13"))],
        commitments=[
            MinutesCommitment(id="C1", topic="T1", what="Cotizar la pintura del salón",
                              owner="person", who="Doña Rosa", due="antes del 15",
                              evidence=ev("01:03")),
            MinutesCommitment(id="C2", topic="T2", what="Hablar con la municipalidad",
                              owner="nobody", who=None, due=None, evidence=ev("01:40")),
            MinutesCommitment(id="C3", topic="T2", what="Enviar la lista de asociados | WhatsApp",
                              owner="recipients", who=None, due="el lunes", evidence=ev("01:59")),
            MinutesCommitment(id="C4", topic="T2", what="Mandar los formularios", owner="speaker",
                              who=None, due=None, evidence=ev("02:01")),
        ],
        pending=[Entry(id="P1", topic="T2", text="¿Dará la municipalidad el permiso?",
                       evidence=ev("01:45"))],
        observations=[Entry(id="O1", topic="T1", text="Don Carlos molesto por la baja asistencia",
                            evidence=ev("00:22"))],
        next_meeting=MinutesNextMeeting(day="el sábado 25", time="a las 3", place="salón comunal"),
        tangents=[Tangent(start="01:10", end="01:18", summary="La boda de la nieta.")],
    )
    return base.model_copy(update=changes)


PROSE = Prose(title="Reunión de la Asociación de Vecinos", summary="La cuota sube a ₡5.000.",
              developments={"T1": "Se habló de pintar el salón.", "T2": None})


PROVENANCE = Provenance(memo_id="abc123", audio_sha256="f00", audio_name="nota.ogg",
                        whisper="whisper-x", llm="qwen-x", prompts="p1", code="c1")


def body(text):
    """Minuta.md without its frontmatter."""
    return text.split("---\n", 2)[2]


def test_minuta_published():
    m = minutes(provenance=PROVENANCE)
    m.agreements[0].evidence[0].verified = True
    text = output.render_minuta(m, PROSE, number=12)

    assert text.startswith("---\nnumero: 12\nfecha: 2026-10-05\n"
                           "titulo: Reunión de la Asociación de Vecinos\n")
    front = yaml.safe_load(text.split("---\n")[1])
    assert front["asistentes"] == ["Don Carlos (presidente)", "Doña Rosa (tesorera)", "Jorge"]
    assert (front["memo_id"], front["audio_sha256"], front["llm"], front["crc_memo"]) == \
        ("abc123", "f00", "qwen-x", "c1")
    assert front["tags"] == ["minuta"]
    text = body(text)
    assert text.startswith("\n# M12 · Minuta — Reunión de la Asociación de Vecinos\n\n"
                           "**Reunión:** ayer, según el audio del 5 oct 2026 · "
                           "**Lugar:** salón comunal · **Presidió:** Don Carlos\n"
                           "**Relato de:** Marta · audio de 28 min\n"
                           "**Asistentes:** Don Carlos (presidente), Doña Rosa (tesorera), Jorge\n")
    assert ("> **Piden a quienes reciben el audio:**\n"
            "> - Enviar la lista de asociados | WhatsApp — **el lunes**") in text
    assert "## Resumen\nLa cuota sube a ₡5.000.\n" in text
    assert ("### 1. Pintura del salón comunal [00:29–01:25]\nSe habló de pintar el salón.\n"
            "Acuerdos: M12-A1, M12-A2 · Compromisos: M12-C1\n") in text
    assert "### 2. Turno de diciembre [01:25–02:06]\nCompromisos: M12-C2, M12-C3, M12-C4\n" in text
    # Verified evidence plain; unverified with ⚠; every mention listed.
    assert "- **M12-A1** Pintar el salón comunal antes de diciembre. — [00:40] «cita 00:40»\n" in text
    assert ("- **M12-A2** La cuota mensual sube a **₡5.000** desde noviembre. — "
            "[00:49] ⚠ «cita 00:49» · [02:13] ⚠ «cita 02:13»\n") in text
    assert ("- **[M12-C1](../../../Compromisos/2026/M12-C1.md)** · Doña Rosa · "
            "Cotizar la pintura del salón · plazo: antes del 15 — [01:03] ⚠ «cita 01:03»") in text
    assert "· sin asignar · Hablar con la municipalidad · plazo: sin fecha —" in text
    assert "· **Quienes reciben el audio** · Enviar la lista" in text
    assert "· Marta · Mandar los formularios ·" in text  # the speaker, by name
    assert "- **M12-P1** ¿Dará la municipalidad el permiso? — [01:45] ⚠ «cita 01:45»" in text
    assert "## Próxima reunión\nEl sábado 25 · a las 3 · salón comunal\n" in text
    assert "- **M12-O1** Don Carlos molesto por la baja asistencia — [00:22]" in text
    assert "## Desvíos del audio\n- [01:10–01:18] La boda de la nieta — se puede saltar\n" in text
    assert text.endswith("---\n*Minuta elaborada automáticamente a partir del relato de Marta; "
                         "no es un acta oficial.\n"
                         "Los minutos [mm:ss] indican dónde verificarlo en el audio.*\n")


def test_minuta_local_has_plain_ids_and_no_links():
    text = output.render_minuta(minutes(), PROSE)
    assert text.startswith("---\nnumero: null\n")
    assert "\n# Minuta — Reunión de la Asociación de Vecinos\n" in text
    assert "- **C1** · Doña Rosa ·" in text and "Compromisos/" not in text
    assert "- **A1** Pintar" in text and "Acuerdos: A1, A2" in text
    assert "memo_id: null" in text  # minutes.json from before Phase 4: no provenance


def test_published_without_date_has_no_commitment_links():
    m = minutes(source=Source(sender=None, memo_date=None, duration="05:00", language="es"))
    assert "- **M3-C1** · Doña Rosa" in output.render_minuta(m, PROSE, number=3)


def test_rendering_is_deterministic():
    m = minutes(provenance=PROVENANCE)
    assert output.render_minuta(m, PROSE, 5) == output.render_minuta(m.model_copy(deep=True), PROSE, 5)


def test_empty_sections_are_left_out():
    empty = minutes(
        source=Source(sender=None, memo_date=None, duration="00:40", language="en"),
        meeting=Meeting(group=None, when=None, place=None, chaired_by=None),
        attendees=[], topics=[], agreements=[], commitments=[], pending=[], observations=[],
        next_meeting=None, tangents=[],
    )
    prose = Prose(title=None, summary=None, developments={})
    assert body(output.render_minuta(empty, prose)) == (
        "\n# Minutes — Meeting\n\n1 min audio\n\n"
        "---\n*Minutes written automatically from a voice memo; not official minutes.\n"
        "The [mm:ss] times show where to check it in the audio.*\n")


def test_partial_header_and_title_fallback():
    m = minutes(
        source=Source(sender=None, memo_date="2026-10-05", duration="1:05:10", language="en"),
        meeting=Meeting(group="Neighbours", when=None, place=None, chaired_by=None),
        attendees=[], next_meeting=MinutesNextMeeting(day=None, time=None, place=None),
    )
    text = body(output.render_minuta(m, Prose(title=None, summary=None, developments={})))
    assert text.startswith("\n# Minutes — Neighbours\n\n"
                           "**Meeting:** per the audio of 5 Oct 2026\n1 h 05 min audio\n\n")
    assert "· The sender · Mandar los formularios · due: no date —" in text  # no name known
    assert "· unassigned · Hablar con la municipalidad ·" in text
    assert "Next meeting" not in text and "Attendees" not in text


def test_recipient_ask_without_due():
    m = minutes(commitments=[MinutesCommitment(id="C1", topic=None, what="Llamar a Jorge",
                                               owner="recipients", who=None, due=None,
                                               evidence=ev("00:10"))])
    assert "> - Llamar a Jorge\n" in output.render_minuta(m, PROSE)


def test_not_a_meeting_recap_has_no_meeting_details():
    prose = PROSE.model_copy(update={"meeting_recap": False, "title": "Cuota de representación"})
    text = output.render_minuta(minutes(), prose)
    assert "es_reunion: false" in text
    assert "\n# Minuta — Cuota de representación\n\n" \
           "**Relato de:** Marta · audio de 28 min del 5 oct 2026\n\n" in text
    for absent in ["**Reunión:**", "Lugar", "Presidió", "Asistentes:**"]:
        assert absent not in body(text)


def test_not_a_meeting_recap_without_date():
    m = minutes(source=Source(sender=None, memo_date=None, duration="05:33", language="es"))
    text = output.render_minuta(m, PROSE.model_copy(update={"meeting_recap": False}))
    assert "\n\naudio de 6 min\n\n" in text


def test_older_prose_without_the_flag_renders_as_a_meeting():
    prose = Prose.model_validate({"title": "x", "summary": None, "developments": {}})
    assert prose.meeting_recap is None
    assert "**Reunión:** ayer" in output.render_minuta(minutes(), prose)


@pytest.mark.parametrize("iso, language, expected", [
    ("2026-10-05", "es", "5 oct 2026"), ("2026-01-31", "en", "31 Jan 2026"),
    ("ayer", "es", "ayer"),
])
def test_format_date(iso, language, expected):
    assert output.format_date(iso, output.labels_for(language)) == expected


@pytest.mark.parametrize("duration, expected", [
    ("00:10", "1 min"), ("27:42", "28 min"), ("59:59", "1 h 00 min"), ("1:05:10", "1 h 05 min"),
])
def test_format_duration(duration, expected):
    assert output.format_duration(duration) == expected


def test_unknown_language_uses_english_labels():
    assert output.labels_for("pt") is output.LABELS["en"]
    assert output.labels_for("es") is output.LABELS["es"]


def test_write_renders_minuta_md(tmp_path):
    (tmp_path / "minutes.json").write_text(minutes().model_dump_json())
    (tmp_path / "prose.json").write_text(json.dumps(PROSE.model_dump()))
    (path,) = output.write(tmp_path)
    assert path.name == "Minuta.md"
    assert path.read_text() == output.render_minuta(minutes(), PROSE)


def test_minutes_from_before_phase_4_still_load_and_render():
    data = minutes().model_dump()
    for item in data["agreements"] + data["commitments"]:
        item["timestamps"] = [e["timestamp"] for e in item.pop("evidence")]
    old = Minutes.model_validate(data)
    assert old.agreements[1].timestamps == ["00:49", "02:13"]
    text = output.render_minuta(old, PROSE)
    assert "- **A2** La cuota mensual sube a **₡5.000** desde noviembre. — [00:49] · [02:13]\n" in text


@pytest.mark.parametrize("value, expected", [("2026-10-05", date(2026, 10, 5)), (None, None),
                                             ("ayer", "ayer")])
def test_yaml_date(value, expected):
    assert output.yaml_date(value) == expected
