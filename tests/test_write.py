import json
from types import SimpleNamespace

import pytest

from crc_memo import summarize
from crc_memo.schemas import Prose
from tests.test_output import minutes


class LLM(list):
    """Fake Ollama answering by schema: `developments` in order, then the overview."""

    def __init__(self, developments, overview=None):
        super().__init__()
        self.developments = list(developments)
        self.overview = overview or {"meeting_recap": True, "title": "Reunión de vecinos",
                                     "summary": "sube a cinco rojos"}

    def __call__(self, messages, schema):
        self.append((schema["title"], messages[0]["content"]))
        answer = ({"development": self.developments.pop(0)} if schema["title"] == "Development"
                  else self.overview)
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))


def write_memo(folder, m, segments):
    (folder / "minutes.json").write_text(m.model_dump_json())
    (folder / "meta.json").write_text(json.dumps({"id": "x", "language": "es"}))
    (folder / "segments.json").write_text(json.dumps(
        [{"start": s, "end": s + 5, "text": f" {t}"} for s, t in segments]))
    return folder


# T1 starts 00:29, T2 01:25 (ends 02:06 but runs to the end); tangent 01:10–01:18.
SEGMENTS = [(10, "saludo"), (29.4, "pintar el salón"), (70, "la boda de la nieta"), (78.4, "flores blancas"),
            (84.9, "cinco rojos de cuota"), (85, "el turno"), (200, "bueno, eso fue todo")]


def test_write_one_call_per_topic_then_overview(tmp_path, monkeypatch, no_thresholds):
    llm = LLM(["se habló de pintar, con cinco rojos", "no se menciona"])
    monkeypatch.setattr(summarize, "_chat", llm)
    progress = []

    prose = summarize.write(write_memo(tmp_path, minutes(), SEGMENTS),
                            lambda done, total: progress.append((done, total)))

    assert [schema for schema, _ in llm] == ["Development", "Development", "Overview"]
    t1, t2, overview = (prompt for _, prompt in llm)
    # Each topic gets its own lines, without the digression and before the next topic starts.
    assert "[00:29] pintar el salón\n[01:24] cinco rojos de cuota\n" in t1
    assert "boda" not in t1 and "flores" not in t1 and "saludo" not in t1 and "el turno" not in t1
    assert "**Pintura del salón comunal** (00:29–01:25)" in t1
    assert "- Agreement: La cuota mensual sube a ₡5.000 desde noviembre." in t1
    assert "- Commitment: Doña Rosa · antes del 15 · Cotizar la pintura del salón" in t1
    assert "- Observation: Don Carlos molesto" in t1
    assert "Pending" not in t1
    # The last topic runs to the end of the memo.
    assert "[01:25] el turno\n[03:20] bueno, eso fue todo" in t2
    assert "- Commitment: nobody named · no deadline · Hablar con la municipalidad" in t2
    assert "- Commitment: the people receiving the audio · el lunes" in t2
    assert "- Commitment: the person speaking · no deadline · Mandar los formularios" in t2
    assert "- Pending: ¿Dará la municipalidad el permiso?" in t2
    assert "Spanish (as spoken in Costa Rica)" in t2
    # The overview sees the developments and every item, not the transcript.
    assert "### Pintura del salón comunal\nSe habló de pintar, con ₡5.000" in overview
    assert "### Turno de diciembre\n(no details)" in overview
    assert "- Agreement: Pintar el salón" in overview and "- Pending:" in overview
    assert "pintar el salón\n" not in overview

    assert prose == Prose(meeting_recap=True, title="Reunión de vecinos", summary="Sube a ₡5.000.",
                          developments={"T1": "Se habló de pintar, con ₡5.000.", "T2": None})
    assert json.loads((tmp_path / "prose.json").read_text()) == prose.model_dump()
    assert summarize.is_written(tmp_path)
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert json.loads((tmp_path / "meta.json").read_text())["llm"]["write"]["calls"] == 3


def test_topic_without_lines_gets_no_call(tmp_path, monkeypatch):
    llm = LLM(["el turno se discutió"],
              overview={"meeting_recap": False, "title": "", "summary": "no se menciona"})
    monkeypatch.setattr(summarize, "_chat", llm)

    prose = summarize.write(write_memo(tmp_path, minutes(), [(85, "el turno")]))

    assert [schema for schema, _ in llm] == ["Development", "Overview"]
    assert prose == Prose(meeting_recap=False, title=None, summary=None,
                          developments={"T1": None, "T2": "El turno se discutió."})


def test_nothing_extracted_means_no_llm_calls(tmp_path, monkeypatch):
    llm = LLM([])
    monkeypatch.setattr(summarize, "_chat", llm)
    empty = minutes(topics=[], agreements=[], commitments=[], pending=[])

    prose = summarize.write(write_memo(tmp_path, empty, SEGMENTS))

    assert llm == []
    assert prose == Prose(title=None, summary=None, developments={})
    assert not (tmp_path / "prose.partial.json").exists()


def test_overview_without_topics(tmp_path, monkeypatch):
    llm = LLM([])
    monkeypatch.setattr(summarize, "_chat", llm)
    summarize.write(write_memo(tmp_path, minutes(topics=[]), SEGMENTS))
    ((schema, prompt),) = llm
    assert "## Topics discussed\n(none)" in prompt


def test_overview_without_items(tmp_path, monkeypatch):
    llm = LLM(["a", "b"])
    monkeypatch.setattr(summarize, "_chat", llm)
    m = minutes(agreements=[], commitments=[], pending=[], observations=[])
    summarize.write(write_memo(tmp_path, m, SEGMENTS))
    assert "## Items\n(none)" in llm[-1][1]
    assert "## Items already extracted for this topic\n(none)" in llm[0][1]


@pytest.mark.parametrize("name", ["develop", "overview"])
def test_prompts_have_no_unfilled_placeholders(name):
    values = {"title": "x", "range": "x", "language": "x", "items": "x", "transcript": "x",
              "topics": "x"}
    text = summarize.load_prompt(name, **values)
    assert "{" not in text
