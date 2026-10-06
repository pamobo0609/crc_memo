import json
from types import SimpleNamespace

import pytest

from crc_memo import summarize
from crc_memo.schemas import (ActionItem, ChunkExtraction, MergedPoint, NextMeeting, Point,
                              Tangent)


def point(ts, text):
    return Point(timestamp=ts, quote=f"«{text}»", text=text)


def task(ts, text, owner="sin asignar", due="sin fecha"):
    return ActionItem(timestamp=ts, quote=f"«{text}»", task=text, owner=owner, due=due)


def chunk(**fields):
    empty = {k: [] for k in ["topics", "participants", "decisions", "action_items",
                             "open_questions", "notable", "tangents", "next_meeting"]}
    return ChunkExtraction(**(empty | fields))


def write_chunks(folder, *chunks):
    folder.mkdir(exist_ok=True)
    (folder / "extractions.json").write_text(json.dumps(
        [{"range": "00:00–05:00", **c.model_dump()} for c in chunks]))
    return folder


class PlanCalls(list):
    pass


@pytest.fixture
def llm(monkeypatch):
    calls = PlanCalls()
    calls.answer = None

    def fake(messages, schema):
        calls.append(messages[0]["content"])
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(calls.answer)))

    monkeypatch.setattr(summarize, "_chat", fake)
    return calls


def groups(*item_lists):
    return [{"fact": f"hecho {i}", "items": items} for i, items in enumerate(item_lists)]


# --- small helpers ------------------------------------------------------------

@pytest.mark.parametrize("ts, seconds", [("05:42", 342), ("1:02:05", 3725), ("abc", float("inf")),
                                          ("", float("inf"))])
def test_timestamp_seconds(ts, seconds):
    assert summarize.timestamp_seconds(ts) == seconds


def test_union_collapses_variants_keeping_the_longest():
    assert summarize._union(["don Carlos", "Doña Rosa", "Don Carlos (presidente)", "", "doña rosa"]) \
        == ["Don Carlos (presidente)", "Doña Rosa"]


@pytest.mark.parametrize("range_, bounds", [("01:10–01:18", ("01:10", "01:18")),
                                             ("01:10 - 01:18", ("01:10", "01:18")),
                                             ("01:10", ("01:10", "01:10"))])
def test_range_bounds(range_, bounds):
    assert summarize._range_bounds(range_) == bounds


def test_merge_tangents():
    original = Tangent(range="01:00–01:30", summary="boda")
    result = summarize._merge_tangents([
        Tangent(range="05:00–06:00", summary="clima"),
        Tangent(range="01:20–02:00", summary="boda otra vez"),  # overlaps: extends
        original,
        Tangent(range="01:25–01:40", summary="dentro"),          # contained: no change
    ])
    assert [(t.range, t.summary) for t in result] == [("01:00–02:00", "boda"), ("05:00–06:00", "clima")]
    assert original.range == "01:00–01:30"  # inputs are not mutated


def test_repair_grouping():
    assert summarize._repair([[2, 2, 9], [2, 1], [0]], 4) == [[2], [1], [3], [4]]


def test_combine_points_keeps_earliest_and_all_times():
    merged = summarize._combine([point("12:40", "La cuota sube otra vez"), point("03:10", "La cuota sube"),
                                 point("03:10", "La cuota sube")])
    assert merged == MergedPoint(timestamps=["03:10", "12:40"], quote="«La cuota sube»", text="La cuota sube")


def test_combine_tasks_takes_the_most_specific_owner_and_due():
    merged = summarize._combine([task("02:00", "Cotizar"), task("09:00", "Cotizar pintura", "Doña Rosa", "el 15")])
    assert (merged.task, merged.owner, merged.due) == ("Cotizar", "Doña Rosa", "el 15")
    vague = summarize._combine([task("02:00", "Cotizar"), task("09:00", "Cotizar")])
    assert (vague.owner, vague.due) == ("sin asignar", "sin fecha")


def test_drop_covered_notable():
    notable = [MergedPoint(timestamps=[ts], quote="", text=ts) for ts in ["00:22", "01:12", "02:27"]]
    meeting = NextMeeting(timestamp="02:27", quote="", day="sábado", time="", place="")
    kept = summarize._drop_covered(notable, [Tangent(range="01:10–01:18", summary="boda")], [meeting])
    assert [p.text for p in kept] == ["00:22"]


# --- the merge step -------------------------------------------------------------

def test_single_chunk_needs_no_llm(llm, tmp_path):
    folder = write_chunks(tmp_path / "memo", chunk(
        decisions=[point("03:10", "Cuota a ₡5.000"), point("00:43", "Pintar el salón")],
        participants=["Don Carlos", "usted", "el speaker"],
    ))
    merged, removed = summarize.merge(folder)

    assert llm == []
    assert removed == 0
    assert [d.text for d in merged.decisions] == ["Pintar el salón", "Cuota a ₡5.000"]  # time order
    assert merged.participants == ["Don Carlos"]
    assert summarize.is_merged(folder)
    assert json.loads((folder / "merged.json").read_text())["decisions"][0]["timestamps"] == ["00:43"]


def test_chunks_with_one_item_each_need_no_llm(llm, tmp_path):
    folder = write_chunks(tmp_path / "memo", chunk(decisions=[point("00:10", "A")]), chunk())
    summarize.merge(folder)
    assert llm == []


def test_multi_chunk_merge_uses_llm_groups(llm, tmp_path):
    folder = write_chunks(
        tmp_path / "memo",
        chunk(decisions=[point("00:43", "Pintar el salón"), point("00:49", "Cuota a cinco rojos")],
              action_items=[task("01:03", "Cotizar pintura", "Doña Rosa", "antes del 15")],
              participants=["don Carlos"], topics=["Salón"],
              next_meeting=[NextMeeting(timestamp="02:00", quote="", day="sábado", time="", place="")]),
        chunk(decisions=[point("02:13", "La cuota sube a cinco rojos")],
              action_items=[task("01:03", "Cotizar la pintura")],
              participants=["Don Carlos (presidente)"], topics=["salón", "Turno"],
              next_meeting=[NextMeeting(timestamp="02:27", quote="", day="sábado 25", time="3 p. m.", place="salón")]),
    )
    llm.answer = {"decisions": groups([1], [2, 3]), "action_items": groups([1, 2]),
                  "open_questions": [], "notable": []}

    merged, removed = summarize.merge(folder)

    assert removed == 2
    assert [(d.timestamps, d.text) for d in merged.decisions] == [
        (["00:43"], "Pintar el salón"), (["00:49", "02:13"], "Cuota a cinco rojos")]
    (only_task,) = merged.action_items
    assert (only_task.owner, only_task.due) == ("Doña Rosa", "antes del 15")
    assert merged.participants == ["Don Carlos (presidente)"]
    assert merged.topics == ["Salón", "Turno"]
    assert merged.next_meeting[0].day == "sábado 25"  # the last mention wins

    prompt = llm[0]
    assert "## decisions\n[1] (00:43) Pintar el salón\n[2] (00:49) Cuota a cinco rojos" in prompt
    assert "[2] (01:03) sin asignar · sin fecha · Cotizar la pintura" in prompt
    assert "## open_questions\n(none)" in prompt
