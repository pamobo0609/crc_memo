import json

import pytest

from crc_memo import output
from crc_memo.schemas import (Entry, Meeting, Minutes, MinutesCommitment, MinutesNextMeeting,
                              Prose, Source, Tangent, Topic)


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
                          timestamps=["00:40"]),
                    Entry(id="A2", topic="T1", text="La cuota mensual sube a ₡5.000 desde noviembre.",
                          timestamps=["00:49", "02:13"])],
        commitments=[
            MinutesCommitment(id="C1", topic="T1", what="Cotizar la pintura del salón",
                              owner="person", who="Doña Rosa", due="antes del 15",
                              timestamps=["01:03"]),
            MinutesCommitment(id="C2", topic="T2", what="Hablar con la municipalidad",
                              owner="nobody", who=None, due=None, timestamps=["01:40"]),
            MinutesCommitment(id="C3", topic="T2", what="Enviar la lista de asociados | WhatsApp",
                              owner="recipients", who=None, due="el lunes", timestamps=["01:59"]),
            MinutesCommitment(id="C4", topic="T2", what="Mandar los formularios", owner="speaker",
                              who=None, due=None, timestamps=["02:01"]),
        ],
        pending=[Entry(id="P1", topic="T2", text="¿Dará la municipalidad el permiso?",
                       timestamps=["01:45"])],
        observations=[Entry(id="O1", topic="T1", text="Don Carlos molesto por la baja asistencia",
                            timestamps=["00:22"])],
        next_meeting=MinutesNextMeeting(day="el sábado 25", time="a las 3", place="salón comunal"),
        tangents=[Tangent(start="01:10", end="01:18", summary="La boda de la nieta.")],
    )
    return base.model_copy(update=changes)


PROSE = Prose(title="Reunión de la Asociación de Vecinos", summary="La cuota sube a ₡5.000.",
              developments={"T1": "Se habló de pintar el salón.", "T2": None})


def test_breve():
    text = output.render(minutes(), PROSE)
    assert text.startswith("# Minuta — Reunión de la Asociación de Vecinos\n\n"
                           "**Reunión:** ayer, según el audio del 5 oct 2026 · "
                           "**Lugar:** salón comunal · **Presidió:** Don Carlos\n"
                           "**Relato de:** Marta · audio de 28 min\n\n")
    assert ("> **Piden a quienes reciben el audio:**\n"
            "> - Enviar la lista de asociados | WhatsApp — **el lunes**") in text
    assert "## Resumen\nLa cuota sube a ₡5.000.\n" in text
    assert "1. Pintar el salón comunal antes de diciembre.\n" in text
    assert "2. La cuota mensual sube a **₡5.000** desde noviembre.\n" in text
    assert ("| Responsable | Compromiso | Plazo |\n|---|---|---|\n"
            "| Doña Rosa | Cotizar la pintura del salón | antes del 15 |\n"
            "| sin asignar | Hablar con la municipalidad | sin fecha |\n"
            "| **Quienes reciben el audio** | Enviar la lista de asociados \\| WhatsApp | el lunes |\n"
            "| Marta | Mandar los formularios | sin fecha |"  # the speaker, by name
            ) in text
    assert "## Pendientes\n- ¿Dará la municipalidad el permiso?\n" in text
    assert "## Próxima reunión\nEl sábado 25 · a las 3 · salón comunal\n" in text
    assert text.endswith("---\n*Minuta elaborada automáticamente a partir del relato de Marta; "
                         "no es un acta oficial.*\n")
    # Only in the completa:
    for absent in ["Asistentes", "Temas tratados", "Observaciones", "Desvíos", "[00:49"]:
        assert absent not in text


def test_completa():
    text = output.render(minutes(), PROSE, full=True)
    assert text.startswith("# Minuta completa — Reunión de la Asociación de Vecinos\n")
    assert "**Asistentes:** Don Carlos (presidente), Doña Rosa (tesorera), Jorge\n" in text
    assert ("### 1. Pintura del salón comunal [00:29–01:25]\nSe habló de pintar el salón.\n"
            "Acuerdos: 1, 2 · Compromisos: Doña Rosa\n\n") in text
    # No desarrollo: heading and references only; the recipients aren't bold here.
    assert ("### 2. Turno de diciembre [01:25–02:06]\n"
            "Compromisos: sin asignar, Quienes reciben el audio, Marta\n") in text
    assert "## Resumen" not in text
    assert "2. La cuota mensual sube a **₡5.000** desde noviembre. [00:49, 02:13]\n" in text
    assert "| Responsable | Compromiso | Plazo | Fuente |\n|---|---|---|---|\n" in text
    assert "| Doña Rosa | Cotizar la pintura del salón | antes del 15 | [01:03] |" in text
    assert "- ¿Dará la municipalidad el permiso? [01:45]\n" in text
    assert "## Observaciones\n- Don Carlos molesto por la baja asistencia [00:22]\n" in text
    assert "## Desvíos del audio\n- [01:10–01:18] La boda de la nieta — se puede saltar\n" in text
    assert text.endswith("no es un acta oficial.\n"
                         "Los minutos [mm:ss] indican dónde verificarlo en el audio.*\n")


def test_empty_sections_are_left_out():
    empty = minutes(
        source=Source(sender=None, memo_date=None, duration="00:40", language="en"),
        meeting=Meeting(group=None, when=None, place=None, chaired_by=None),
        attendees=[], topics=[], agreements=[], commitments=[], pending=[], observations=[],
        next_meeting=None, tangents=[],
    )
    prose = Prose(title=None, summary=None, developments={})
    assert output.render(empty, prose) == (
        "# Minutes — Meeting\n\n1 min audio\n\n"
        "---\n*Minutes written automatically from a voice memo; not official minutes.*\n")
    assert output.render(empty, prose, full=True) == (
        "# Full minutes — Meeting\n\n1 min audio\n\n"
        "---\n*Minutes written automatically from a voice memo; not official minutes.\n"
        "The [mm:ss] times show where to check it in the audio.*\n")


def test_partial_header_and_title_fallback():
    m = minutes(
        source=Source(sender=None, memo_date="2026-10-05", duration="1:05:10", language="en"),
        meeting=Meeting(group="Neighbours", when=None, place=None, chaired_by=None),
        attendees=[], next_meeting=MinutesNextMeeting(day=None, time=None, place=None),
    )
    text = output.render(m, Prose(title=None, summary=None, developments={}), full=True)
    assert text.startswith("# Full minutes — Neighbours\n\n"
                           "**Meeting:** per the audio of 5 Oct 2026\n1 h 05 min audio\n\n")
    assert "| The sender | Mandar los formularios | no date | [02:01] |" in text  # no name known
    assert "| unassigned | Hablar con la municipalidad |" in text
    assert "Next meeting" not in text
    assert "Attendees" not in text


def test_recipient_ask_without_due():
    m = minutes(commitments=[MinutesCommitment(id="C1", topic=None, what="Llamar a Jorge",
                                               owner="recipients", who=None, due=None,
                                               timestamps=["00:10"])])
    assert "> - Llamar a Jorge\n" in output.render(m, PROSE)


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


def test_write_renders_both_files(tmp_path):
    (tmp_path / "minutes.json").write_text(minutes().model_dump_json())
    (tmp_path / "prose.json").write_text(json.dumps(PROSE.model_dump()))
    breve, completa = output.write(tmp_path)
    assert breve.name == "minuta_breve.md" and completa.name == "minuta_completa.md"
    assert breve.read_text() == output.render(minutes(), PROSE)
    assert completa.read_text() == output.render(minutes(), PROSE, full=True)


def test_not_a_meeting_recap_has_no_meeting_details():
    prose = PROSE.model_copy(update={"meeting_recap": False, "title": "Cuota de representación"})
    text = output.render(minutes(), prose, full=True)
    assert text.startswith("# Minuta completa — Cuota de representación\n\n"
                           "**Relato de:** Marta · audio de 28 min del 5 oct 2026\n\n")
    for absent in ["**Reunión:**", "Lugar", "Presidió", "Asistentes"]:
        assert absent not in text


def test_not_a_meeting_recap_without_date():
    m = minutes(source=Source(sender=None, memo_date=None, duration="05:33", language="es"))
    text = output.render(m, PROSE.model_copy(update={"meeting_recap": False}))
    assert "\n\naudio de 6 min\n\n" in text


def test_older_prose_without_the_flag_renders_as_a_meeting():
    prose = Prose.model_validate({"title": "x", "summary": None, "developments": {}})
    assert prose.meeting_recap is None
    assert "**Reunión:** ayer" in output.render(minutes(), prose)
