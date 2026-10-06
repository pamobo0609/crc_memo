import json
from types import SimpleNamespace

import pytest

from crc_memo import summarize
from crc_memo.schemas import (ChunkExtraction, Commitment, MeetingInfo, NextMeeting, Point,
                              Tangent, Topic, TopicSpan)


def point(ts, text):
    return Point(timestamp=ts, quote=f"«{text}»", text=text)


def commitment(ts, what, who="", due="", for_recipients=False):
    return Commitment(timestamp=ts, quote=f"«{what}»", what=what, who=who,
                      for_recipients=for_recipients, due=due)


def chunk(**fields):
    empty = {k: [] for k in ChunkExtraction.model_fields}
    return ChunkExtraction(**(empty | fields))


def write_memo(folder, *chunks, meta=None, segments_end=157.0):
    folder.mkdir(exist_ok=True)
    (folder / "extractions.json").write_text(json.dumps(
        [{"range": "00:00–05:00", **c.model_dump()} for c in chunks]))
    (folder / "segments.json").write_text(json.dumps(
        [{"start": 0.0, "end": segments_end, "text": "…"}] if segments_end else []))
    (folder / "meta.json").write_text(json.dumps(meta or {"id": "x", "language": "es"}))
    return folder


class LLM(list):
    """Fake merge LLM: records prompts, answers with `self.plan` (a MergePlan as dict)."""
    plan = None

    def __call__(self, messages, schema):
        self.append(messages[0]["content"])
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.plan)))


@pytest.fixture
def llm(monkeypatch):
    fake = LLM()
    monkeypatch.setattr(summarize, "_chat", fake)
    return fake


def groups(*item_lists):
    return [{"fact": f"hecho {i}", "items": items} for i, items in enumerate(item_lists)]


def no_groups(**fields):
    plan = {f: [] for f in summarize.GROUPED_FIELDS}
    return plan | fields


# --- helpers ------------------------------------------------------------------------

@pytest.mark.parametrize("ts, seconds", [("05:42", 342), ("1:02:05", 3725), ("abc", float("inf")),
                                          ("", float("inf"))])
def test_timestamp_seconds(ts, seconds):
    assert summarize.timestamp_seconds(ts) == seconds


@pytest.mark.parametrize("text, expected", [
    ("La cuota sube a cinco rojos", "La cuota sube a ₡5.000"),
    ("medio palo para el turno", "₡500.000 para el turno"),
    ("faltan 50 tucanes", "faltan ₡250.000"),
    ("Un Tucán y dos tejas", "₡5.000 y ₡200"),
    ("un carro rojo", "un carro rojo"),  # no amount before "rojo": left alone
])
def test_normalize_money(text, expected):
    assert summarize.normalize_money(text) == expected


def test_union_collapses_variants_keeping_the_longest():
    assert summarize._union(["don Carlos", "Doña Rosa", "Don Carlos (presidente)", "", "doña rosa"]) \
        == ["Don Carlos (presidente)", "Doña Rosa"]


@pytest.mark.parametrize("text, expected", [
    ("Doña Rosa", "Doña Rosa"), ("  ", None), ("No se menciona", None), ("sin fecha", None),
])
def test_value(text, expected):
    assert summarize._value(text) == expected


def test_vague_due_becomes_none():
    assert summarize._value("Ahorita", summarize.VAGUE_DUE) is None
    assert summarize._value("el lunes", summarize.VAGUE_DUE) == "el lunes"


def test_sentence_capitalizes_and_normalizes_money():
    assert summarize._sentence(" se acordó cinco rojos ") == "Se acordó ₡5.000"


def test_merge_tangents():
    original = Tangent(start="01:00", end="01:30", summary="boda")
    result = summarize._merge_tangents([
        Tangent(start="05:00", end="06:00", summary="clima"),
        Tangent(start="01:20", end="02:00", summary="boda otra vez"),  # overlaps: extends
        original,
        Tangent(start="01:25", end="01:40", summary="dentro"),          # contained: no change
    ])
    assert [(t.start, t.end, t.summary) for t in result] == [("01:00", "02:00", "Boda"),
                                                             ("05:00", "06:00", "Clima")]
    assert original.end == "01:30"  # inputs are not mutated


def test_repair_grouping():
    assert summarize._repair([[2, 2, 9], [2, 1], [0]], 4) == [[2], [1], [3], [4]]


def test_combine_commitment_takes_the_most_specific_values():
    combined = summarize._combine_commitment([
        commitment("09:00", "cotizar pintura", "Doña Rosa", "el 15"),
        commitment("02:00", "cotizar", due="ahorita", for_recipients=True),
    ])
    assert combined == {"what": "Cotizar", "who": "Doña Rosa", "for_recipients": True,
                        "due": "el 15", "timestamps": ["02:00", "09:00"]}


def test_recipient_pronoun_in_who_means_for_recipients():
    combined = summarize._combine_commitment([commitment("01:59", "Enviar la lista", who="Ustedes")])
    assert (combined["who"], combined["for_recipients"]) == (None, True)


def test_topic_of():
    topics = [Topic(id="T1", title="a", start="01:00", end="03:00"),
              Topic(id="T2", title="b", start="03:00", end="05:00")]
    assert summarize._topic_of("02:00", topics) == "T1"
    assert summarize._topic_of("03:30", topics) == "T2"
    assert summarize._topic_of("00:10", topics) == "T1"  # before the first topic: the first
    assert summarize._topic_of("00:10", []) is None


# --- the merge step ----------------------------------------------------------------

def test_single_chunk_builds_minutes_without_llm(llm, tmp_path):
    folder = write_memo(
        tmp_path / "memo",
        chunk(
            meeting=[MeetingInfo(group="Asociación", when="ayer", place="No se menciona", chaired_by="")],
            topics=[TopicSpan(start="02:00", end="02:30", title="turno"),
                    TopicSpan(start="00:30", end="00:40", title="pintura del salón")],
            attendees=["Don Carlos", "usted", "el speaker"],
            agreements=[point("03:10", "cuota a cinco rojos"), point("00:43", "pintar el salón")],
            commitments=[commitment("01:59", "Enviar la lista", due="el lunes", for_recipients=True),
                         commitment("02:06", "Mandar fotos", "Doña Lupe", "ahorita")],
            observations=[point("00:22", "Don Carlos molesto"), point("01:12", "repite la boda"),
                          point("02:27", "repite la próxima reunión")],
            tangents=[Tangent(start="01:10", end="01:18", summary="la boda")],
            next_meeting=[NextMeeting(timestamp="02:27", quote="", day="sábado 25", time="", place="salón")],
        ),
        meta={"id": "x", "language": "es", "sender": "Marta",
              "transcription": {"audio_seconds": 1662.0}},
    )
    minutes, removed = summarize.merge(folder)

    assert llm == []
    assert removed == 2  # the two observations that only repeated a tangent / the next meeting
    assert minutes.source.model_dump() == {"sender": "Marta", "memo_date": None,
                                           "duration": "27:42", "language": "es"}
    assert minutes.meeting.model_dump() == {"group": "Asociación", "when": "ayer",
                                            "place": None, "chaired_by": None}
    assert minutes.attendees == ["Don Carlos"]
    assert [(t.id, t.title, t.start, t.end) for t in minutes.topics] == [
        ("T1", "Pintura del salón", "00:30", "02:00"),  # ends where the next topic starts
        ("T2", "Turno", "02:00", "03:10"),              # last: runs to its last item
    ]
    assert [(a.id, a.topic, a.text) for a in minutes.agreements] == [
        ("A1", "T1", "Pintar el salón"), ("A2", "T2", "Cuota a ₡5.000")]
    c1, c2 = minutes.commitments
    assert (c1.id, c1.who, c1.for_recipients, c1.due) == ("C1", None, True, "el lunes")
    assert (c2.who, c2.due) == ("Doña Lupe", None)
    assert [o.text for o in minutes.observations] == ["Don Carlos molesto"]
    assert minutes.next_meeting.model_dump() == {"day": "sábado 25", "time": None, "place": "salón"}
    assert summarize.is_merged(folder)
    saved = json.loads((folder / "minutes.json").read_text())
    assert saved["agreements"][1]["text"] == "Cuota a ₡5.000"


def test_empty_memo(llm, tmp_path):
    minutes, removed = summarize.merge(write_memo(tmp_path / "memo", chunk(), segments_end=None))
    assert (minutes.topics, minutes.next_meeting, removed) == ([], None, 0)
    assert minutes.source.duration == "00:00"


def test_chunks_with_one_item_each_need_no_llm(llm, tmp_path):
    summarize.merge(write_memo(tmp_path / "memo", chunk(agreements=[point("00:10", "A")]), chunk()))
    assert llm == []


def test_multi_chunk_merge_uses_llm_groups(llm, tmp_path):
    folder = write_memo(
        tmp_path / "memo",
        chunk(topics=[TopicSpan(start="00:30", end="01:20", title="Cuota")],
              agreements=[point("00:43", "Pintar el salón"), point("00:49", "Cuota a cinco rojos")],
              commitments=[commitment("01:03", "Cotizar pintura", "Doña Rosa", "antes del 15")],
              attendees=["don Carlos"],
              next_meeting=[NextMeeting(timestamp="02:00", quote="", day="sábado", time="", place="")]),
        chunk(topics=[TopicSpan(start="01:00", end="02:30", title="La cuota")],
              agreements=[point("02:13", "La cuota sube a cinco rojos")],
              commitments=[commitment("01:03", "Cotizar la pintura")],
              attendees=["Don Carlos (presidente)"],
              next_meeting=[NextMeeting(timestamp="02:27", quote="", day="sábado 25", time="3 p. m.", place="salón")]),
    )
    llm.plan = no_groups(topics=groups([1, 2]), agreements=groups([1], [2, 3]),
                         commitments=groups([1, 2]))

    minutes, removed = summarize.merge(folder)

    assert removed == 3
    assert [(t.title, t.start, t.end) for t in minutes.topics] == [("Cuota", "00:30", "02:30")]
    assert [(a.timestamps, a.text) for a in minutes.agreements] == [
        (["00:43"], "Pintar el salón"), (["00:49", "02:13"], "Cuota a ₡5.000")]
    (only,) = minutes.commitments
    assert (only.who, only.due) == ("Doña Rosa", "antes del 15")
    assert minutes.attendees == ["Don Carlos (presidente)"]
    assert minutes.next_meeting.day == "sábado 25"  # the last mention wins

    prompt = llm[0]
    assert "## topics\n[1] (00:30–01:20) Cuota\n[2] (01:00–02:30) La cuota" in prompt
    assert "## agreements\n[1] (00:43) Pintar el salón\n[2] (00:49) Cuota a cinco rojos" in prompt
    assert "[2] (01:03) nobody named · no deadline · Cotizar la pintura" in prompt
    assert "## pending\n(none)" in prompt


def test_describe_recipient_commitment():
    item = commitment("01:59", "Enviar la lista", due="el lunes", for_recipients=True)
    assert summarize._describe("commitments", item) == "(01:59) recipients · el lunes · Enviar la lista"
