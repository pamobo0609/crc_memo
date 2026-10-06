import json
from types import SimpleNamespace

import pytest

from crc_memo import summarize
from crc_memo.schemas import (ChunkExtraction, Commitment, Evidence, MeetingInfo, Minutes,
                              MinutesCommitment, NextMeeting, Point, Tangent, Topic, TopicSpan)
from crc_memo.transcribe import Segment


def ev(*timestamps):
    """Evidence for made-up items: a placeholder quote at each time."""
    return [Evidence(timestamp=ts, quote=f"cita {ts}") for ts in timestamps]


def point(ts, text):
    return Point(timestamp=ts, quote=f"«{text}»", text=text)


def commitment(ts, what, who="", due="", owner=None):
    owner = owner or ("person" if who else "nobody")
    return Commitment(timestamp=ts, quote=f"«{what}»", what=what, owner=owner, who=who, due=due)


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
    """Fake merge LLM: records merge prompts and answers with `self.plan` (a MergePlan as dict);
    owner checks are recorded in `self.checks` and answered from `self.owners`, in order."""
    plan = None

    def __init__(self):
        super().__init__()
        self.checks, self.owners = [], []

    def __call__(self, messages, schema):
        if schema["title"] == "OwnerCheck":
            self.checks.append(messages[0]["content"])
            answer = self.owners.pop(0)
        else:
            self.append(messages[0]["content"])
            answer = self.plan
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))


def owner(role, who="", reported=False):
    return {"reported_speech": reported, "owner": role, "who": who}


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
        commitment("02:00", "cotizar.", due="ahorita", owner="recipients"),
    ])
    assert combined == {"what": "Cotizar", "owner": "person", "who": "Doña Rosa",  # name wins
                        "due": "el 15", "evidence": [
                            Evidence(timestamp="02:00", quote="«cotizar.»"),
                            Evidence(timestamp="09:00", quote="«cotizar pintura»")]}


@pytest.mark.parametrize("mentions, owner", [
    ([("", "nobody"), ("", "speaker"), ("", "recipients")], "speaker"),  # first role said
    ([("Ustedes", "person")], "recipients"),  # a pronoun in who overrides the model's choice
    ([("la persona que habla", "person")], "speaker"),
    ([("", "person")], "nobody"),  # "person" without a name
    ([("no se menciona", "nobody")], "nobody"),
])
def test_commitment_owner(mentions, owner):
    combined = summarize._combine_commitment(
        [commitment(f"0{n}:00", "Enviar la lista", who=who, owner=role)
         for n, (who, role) in enumerate(mentions)])
    assert (combined["owner"], combined["who"]) == (owner, None)


@pytest.mark.parametrize("text, expected", [
    ("No se menciona quién no ha presentado nada.", None), ("no especificado", None),
    ("No especificada", None), ("Not mentioned", None), ("  ", None),
    ("No se sabe si la muni da el permiso", "No se sabe si la muni da el permiso"),
])
def test_placeholders(text, expected):
    assert summarize._value(text) == expected


@pytest.mark.parametrize("text, period, expected", [
    ("cuota a cinco rojos", True, "Cuota a ₡5.000."), ("Pintar el salón.", False, "Pintar el salón"),
    ("¿Dará el permiso?", True, "¿Dará el permiso?"), ("", True, ""),
])
def test_sentence(text, period, expected):
    assert summarize._sentence(text, period) == expected


def test_topic_of():
    topics = [Topic(id="T1", title="a", start="01:00", end="03:00"),
              Topic(id="T2", title="b", start="03:00", end="05:00")]
    assert summarize._topic_of("02:00", topics) == "T1"
    assert summarize._topic_of("03:30", topics) == "T2"
    assert summarize._topic_of("00:10", topics) == "T1"  # before the first topic: the first
    assert summarize._topic_of("00:10", []) is None


# --- the merge step ----------------------------------------------------------------

def test_single_chunk_builds_minutes_without_llm(llm, tmp_path, no_thresholds):
    folder = write_memo(
        tmp_path / "memo",
        chunk(
            meeting=[MeetingInfo(group="Asociación", when="ayer", place="No se menciona",
                                 chaired_by="no especificado")],
            topics=[TopicSpan(start="02:00", end="02:30", title="turno"),
                    TopicSpan(start="00:30", end="00:40", title="pintura del salón")],
            attendees=["Don Carlos", "usted", "el speaker"],
            agreements=[point("03:10", "cuota a cinco rojos"), point("00:43", "pintar el salón")],
            commitments=[commitment("01:59", "Enviar la lista", due="el lunes", owner="recipients"),
                         commitment("02:06", "Mandar fotos", "Doña Lupe", "ahorita"),
                         commitment("02:08", "No se menciona", owner="speaker")],
            pending=[point("01:40", "No se menciona si se acepta.")],
            observations=[point("00:22", "Don Carlos molesto"), point("01:12", "repite la boda"),
                          point("02:27", "repite la próxima reunión")],
            tangents=[Tangent(start="01:10", end="01:18", summary="la boda")],
            next_meeting=[NextMeeting(timestamp="02:27", quote="", day="sábado 25", time="", place="salón")],
        ),
        meta={"id": "x", "language": "es", "sender": "Marta",
              "transcription": {"audio_seconds": 1662.0}},
    )
    llm.owners = [owner("recipients"), owner("person", "Doña Lupe")]
    minutes, removed = summarize.merge(folder)

    assert llm == []  # no merge plan for one chunk; only the owner checks
    assert len(llm.checks) == 2
    assert "## Commitment\nEnviar la lista\n" in llm.checks[0]
    # The two observations that only repeated a tangent / the next meeting, and the two
    # placeholder items ("No se menciona…").
    assert removed == 4
    assert minutes.pending == []
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
        ("A1", "T1", "Pintar el salón."), ("A2", "T2", "Cuota a ₡5.000.")]
    c1, c2 = minutes.commitments
    assert (c1.id, c1.owner, c1.who, c1.due) == ("C1", "recipients", None, "el lunes")
    assert (c2.owner, c2.who, c2.due) == ("person", "Doña Lupe", None)
    assert [o.text for o in minutes.observations] == ["Don Carlos molesto."]
    assert minutes.next_meeting.model_dump() == {"day": "sábado 25", "time": None, "place": "salón"}
    assert summarize.is_merged(folder)
    saved = json.loads((folder / "minutes.json").read_text())
    assert saved["agreements"][1]["text"] == "Cuota a ₡5.000."


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
    llm.owners = [owner("person", "Doña Rosa")]

    minutes, removed = summarize.merge(folder)

    assert removed == 3
    assert [(t.title, t.start, t.end) for t in minutes.topics] == [("Cuota", "00:30", "02:30")]
    assert [(a.timestamps, a.text) for a in minutes.agreements] == [
        (["00:43"], "Pintar el salón."), (["00:49", "02:13"], "Cuota a ₡5.000.")]
    (only,) = minutes.commitments
    assert (only.who, only.due) == ("Doña Rosa", "antes del 15")
    assert minutes.attendees == ["Don Carlos (presidente)"]
    assert minutes.next_meeting.day == "sábado 25"  # the most specific mention wins

    prompt = llm[0]
    assert "## topics\n[1] (00:30–01:20) Cuota\n[2] (01:00–02:30) La cuota" in prompt
    assert "## agreements\n[1] (00:43) Pintar el salón\n[2] (00:49) Cuota a cinco rojos" in prompt
    assert "[2] (01:03) nobody named · no deadline · Cotizar la pintura" in prompt
    assert "## pending\n(none)" in prompt


@pytest.mark.parametrize("owner, who", [("recipients", "the people receiving the audio"),
                                        ("speaker", "the person speaking")])
def test_describe_commitment_roles(owner, who):
    item = commitment("01:59", "Enviar la lista", due="el lunes", owner=owner)
    assert summarize._describe("commitments", item) == f"(01:59) {who} · el lunes · Enviar la lista"


@pytest.mark.parametrize("mentions, expected", [
    # (timestamp, day, time, place)
    ([("16:52", "el 5 de diciembre", "", ""), ("24:00", "diciembre", "", "")], "el 5 de diciembre"),
    ([("01:00", "sábado", "a las 3", ""), ("02:00", "sábado", "", "")], "sábado"),
    ([("01:00", "el sábado 25", "", ""), ("02:00", "el domingo 26", "", "")], "el domingo 26"),
])
def test_next_meeting_is_the_most_specific_mention(mentions, expected):
    meetings = [NextMeeting(timestamp=ts, quote="", day=d, time=t, place=p) for ts, d, t, p in mentions]
    best = max(meetings, key=summarize._specificity)
    assert best.day == expected
    if expected == "sábado":
        assert best.time == "a las 3"


def span(start, end, title="x"):
    return {"title": title, "start": start, "end": end}


@pytest.mark.parametrize("topics, expected", [
    # a 20 s topic joins the one before it
    ([span("00:00", "05:00", "a"), span("05:00", "05:20", "b"), span("05:20", "09:00", "c")],
     [("a", "00:00", "05:20"), ("c", "05:20", "09:00")]),
    # a short first topic joins the next one
    ([span("00:19", "00:40", "a"), span("00:40", "04:00", "b")], [("b", "00:19", "04:00")]),
    # several short ones in a row all join the same topic
    ([span("10:00", "11:05", "a"), span("11:05", "11:30", "b"), span("11:30", "11:50", "c")],
     [("a", "10:00", "11:50")]),
    ([span("00:00", "00:30", "only")], [("only", "00:00", "00:30")]),  # nothing to join
    ([], []),
])
def test_fold_short_topics(topics, expected):
    assert [(t["title"], t["start"], t["end"]) for t in summarize._fold_short_topics(topics)] == expected


def test_short_tangents_are_dropped():
    result = summarize._merge_tangents([Tangent(start="11:34", end="11:37", summary="afectado"),
                                        Tangent(start="08:30", end="08:49", summary="árboles")])
    assert [t.summary for t in result] == ["Árboles"]


# --- owner verification -------------------------------------------------------------

LINES = [Segment(s, s + 15, f"línea {s}") for s in range(0, 120, 15)]


def test_context_is_the_line_with_one_before_and_after():
    assert summarize._context("00:47", LINES) == "[00:30] línea 30\n[00:45] línea 45\n[01:00] línea 60"
    assert summarize._context("00:05", LINES) == "[00:00] línea 0\n[00:15] línea 15"
    assert summarize._context("abc", LINES) == "[01:30] línea 90\n[01:45] línea 105"  # unparseable: last


@pytest.mark.parametrize("answer, expected", [
    (owner("recipients"), ("recipients", None)),
    (owner("speaker", "Doña Rosa"), ("speaker", None)),  # who only counts for "person"
    (owner("person", "el desarrollador"), ("person", "el desarrollador")),
    (owner("person", ""), ("nobody", None)),             # a person without a name
    (owner("person", "ustedes"), ("recipients", None)),  # pronouns mean the role
    (owner("person", "la persona que habla"), ("speaker", None)),
    (owner("nobody", reported=True), ("nobody", None)),
])
def test_verify_owner(llm, answer, expected):
    llm.owners = [answer]
    c = MinutesCommitment(id="C1", topic=None, what="Abrir las calles", owner="recipients",
                          who=None, due=None, evidence=ev("00:47"))
    stats = summarize.LLMStats()
    checked = summarize._verify_owner(c, LINES, "Spanish", stats)
    assert (checked.owner, checked.who) == expected
    assert stats.calls == 1
    (prompt,) = llm.checks
    assert "[00:45] línea 45" in prompt and "in Spanish" in prompt


def test_no_owner_checks_without_a_transcript(llm, tmp_path):
    folder = write_memo(tmp_path / "memo", chunk(commitments=[commitment("01:00", "Cotizar", "Rosa")]),
                        segments_end=None)
    (c,) = summarize.merge(folder)[0].commitments
    assert (c.owner, c.who, llm.checks) == ("person", "Rosa", [])


# --- evidence and provenance (4a) ---------------------------------------------------

TRANSCRIPT = [Segment(0, 12, "Buenos días vecinos, les cuento cómo nos fue."),
              Segment(40, 52, "Doña Rosa va a cotizar la pintura antes del quince."),
              Segment(52, 60, "Y el desarrollador tiene que abrir las calles."),
              Segment(200, 210, "Eso fue todo, pura vida.")]


@pytest.mark.parametrize("quote, timestamp, expected", [
    ("Doña Rosa va a cotizar la pintura", "00:40", True),           # exact
    ("dona rosa va a cotizar la pintura", "00:41", True),           # accents/case don't matter
    ("Rosa va cotizar la pintura antes del 15", "00:40", True),      # small differences: fuzzy
    ("el desarrollador tiene que abrir las calles", "00:52", True),  # neighbouring line
    ("el ICE va a poner la luz mañana", "00:40", False),            # not said
    ("pura vida", "00:40", False),                                  # said, but much later
    ("pura vida", "03:25", True),
    ("", "00:40", False),
    ("cotizar la pintura", "abc", False),                           # unparseable time
])
def test_verify_quote(quote, timestamp, expected):
    assert summarize.verify_quote(quote, timestamp, TRANSCRIPT) is expected


def test_timeline_keeps_the_first_quote_per_time():
    items = [point("01:00", "b"), point("00:10", "a"), point("01:00", "otra")]
    _, evidence = summarize._timeline(items)
    assert [(e.timestamp, e.quote) for e in evidence] == [("00:10", "«a»"), ("01:00", "«b»")]


def test_merge_verifies_evidence_and_records_provenance(llm, tmp_path, no_thresholds, monkeypatch):
    monkeypatch.setattr(summarize, "code_version", lambda: "abc123")
    folder = write_memo(
        tmp_path / "memo",
        chunk(agreements=[Point(timestamp="00:00", quote="les cuento cómo nos fue", text="Cuento"),
                          Point(timestamp="00:05", quote="frase inventada por el modelo", text="Otro")]),
        meta={"id": "abc", "sha256": "abcdef", "source_name": "nota.ogg", "language": "es",
              "transcription": {"model": "whisper-x"}},
    )
    (folder / "segments.json").write_text(json.dumps(
        [{"start": 0.0, "end": 12.0, "text": " Buenos días vecinos, les cuento cómo nos fue."}]))

    minutes, _ = summarize.merge(folder)

    assert [e.evidence[0].verified for e in minutes.agreements] == [True, False]
    assert minutes.agreements[0].timestamps == ["00:00"]
    p = minutes.provenance
    assert (p.memo_id, p.audio_sha256, p.audio_name, p.whisper, p.code) == \
        ("abc", "abcdef", "nota.ogg", "whisper-x", "abc123")
    assert p.llm == summarize.config.LLM_MODEL and len(p.prompts) == 12
    saved = json.loads((folder / "minutes.json").read_text())
    assert saved["agreements"][0]["evidence"][0] == {"timestamp": "00:00",
                                                     "quote": "les cuento cómo nos fue",
                                                     "verified": True}


def test_prompts_hash_changes_with_any_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(summarize.config, "PROMPTS_DIR", tmp_path)
    (tmp_path / "a.md").write_text("uno")
    first = summarize.prompts_hash()
    assert summarize.prompts_hash() == first  # deterministic
    (tmp_path / "a.md").write_text("dos")
    assert summarize.prompts_hash() != first


def test_code_version_in_this_checkout():
    version = summarize.code_version()
    assert version is None or len(version.removesuffix("+dirty")) == 12


@pytest.mark.parametrize("status, expected", [("", "0123456789ab"), (" M crc_memo/x.py", "0123456789ab+dirty")])
def test_code_version_marks_uncommitted_changes(monkeypatch, status, expected):
    answers = iter(["0123456789ab\n", status])
    monkeypatch.setattr(summarize.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stdout=next(answers)))
    assert summarize.code_version() == expected


@pytest.mark.parametrize("error", [OSError("no git"), summarize.subprocess.CalledProcessError(128, "git")])
def test_code_version_outside_git(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(summarize.subprocess, "run", fail)
    assert summarize.code_version() is None


def test_older_minutes_without_provenance_still_load(llm, tmp_path, no_thresholds):
    minutes, _ = summarize.merge(write_memo(tmp_path / "memo", chunk()))
    data = minutes.model_dump()
    del data["provenance"]  # minutes.json written before Phase 4
    assert Minutes.model_validate(data).provenance is None
