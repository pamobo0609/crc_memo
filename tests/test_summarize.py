import json
from types import SimpleNamespace

import ollama
import pytest

from crc_memo import config, summarize
from crc_memo.schemas import ChunkExtraction, Commitment
from crc_memo.transcribe import Segment

EXTRACTION = ChunkExtraction(
    meeting=[],
    topics=[],
    attendees=["Doña Rosa"],
    agreements=[],
    commitments=[Commitment(timestamp="01:03", quote="Doña Rosa va a cotizar",
                            what="Cotizar la pintura", who="Doña Rosa", for_recipients=False,
                            due="antes del 15")],
    pending=[],
    observations=[],
    tangents=[],
    next_meeting=[],
)


def reply(content: str):
    return SimpleNamespace(message=SimpleNamespace(content=content))


class FakeChat(list):
    """Fake Ollama: records calls; answers with queued replies, else a valid extraction."""

    def __init__(self):
        super().__init__()
        self.queue = []

    def __call__(self, messages, schema):
        self.append({"messages": list(messages), "schema": schema})
        return reply(self.queue.pop(0) if self.queue else EXTRACTION.model_dump_json())


@pytest.fixture
def chat_calls(monkeypatch):
    fake = FakeChat()
    monkeypatch.setattr(summarize, "_chat", fake)
    return fake


def segs(*starts, length=10):
    return [Segment(s, s + length, f"línea {i}") for i, s in enumerate(starts)]


# --- chunking ---------------------------------------------------------------

def test_chunk_empty():
    assert summarize.chunk_segments([], seconds=300) == []


def test_chunk_everything_fits():
    (chunk,) = summarize.chunk_segments(segs(0, 10, 20), seconds=300)
    assert len(chunk.segments) == 3


def test_chunks_overlap_by_one_segment():
    chunks = summarize.chunk_segments(segs(0, 10, 20, 30, 40, 50), seconds=30)
    assert [[s.start for s in c.segments] for c in chunks] == [[0, 10, 20], [20, 30, 40], [40, 50]]


def test_long_segment_gets_its_own_chunk():
    long_one = [Segment(0, 400, "muy largo"), Segment(400, 410, "corto")]
    chunks = summarize.chunk_segments(long_one, seconds=300)
    assert [len(c.segments) for c in chunks] == [1, 1]  # still progresses, no endless loop


def test_chunk_size_read_from_config_at_call_time(monkeypatch):
    monkeypatch.setattr(config, "CHUNK_SECONDS", 15)
    assert len(summarize.chunk_segments(segs(0, 10, 20, 30))) > 1


def test_chunk_range_and_text():
    chunk = summarize.Chunk([Segment(5, 15, "Hola."), Segment(75, 80, "Pura vida.")])
    assert chunk.range == "00:05–01:20"
    assert chunk.text == "[00:05] Hola.\n[01:15] Pura vida."


# --- prompts ----------------------------------------------------------------

def test_load_prompt_fills_placeholders_and_keeps_other_braces(monkeypatch, tmp_path):
    (tmp_path / "p.md").write_text('Hola {name}. JSON: {"a": 1}')
    monkeypatch.setattr(config, "PROMPTS_DIR", tmp_path)
    assert summarize.load_prompt("p", name="Marta") == 'Hola Marta. JSON: {"a": 1}'


def test_extract_prompt_has_no_unfilled_placeholders():
    prompt = summarize.load_prompt("extract", part=1, parts=2, range="00:00–05:00",
                                   language="Spanish", glossary="", transcript="[00:00] Hola.")
    for name in ["part", "parts", "range", "language", "glossary", "transcript"]:
        assert "{" + name + "}" not in prompt


def test_glossary_is_empty_until_phase_3_5():
    assert summarize.glossary_notes("brete chunche") == ""


# --- talking to Ollama --------------------------------------------------------

def test_chat_sends_settings(monkeypatch):
    seen = {}
    monkeypatch.setattr(ollama, "chat", lambda **kw: seen.update(kw) or "response")
    assert summarize._chat([{"role": "user", "content": "hola"}], {"type": "object"}) == "response"
    assert seen["model"] == config.LLM_MODEL
    assert seen["think"] is False
    assert seen["format"] == {"type": "object"}
    assert seen["options"] == {"num_ctx": config.LLM_NUM_CTX, "num_predict": config.LLM_MAX_OUTPUT_TOKENS,
                               "temperature": config.LLM_TEMPERATURE, "seed": config.LLM_SEED}


@pytest.mark.parametrize("error, message", [
    (ConnectionError("down"), "brew services start ollama"),
    (ollama.ResponseError("model not found", 404), "ollama pull"),
    (ollama.ResponseError("boom", 500), "Ollama error: boom"),
])
def test_chat_errors_are_actionable(monkeypatch, error, message):
    def broken(**kw):
        raise error
    monkeypatch.setattr(ollama, "chat", broken)
    with pytest.raises(summarize.SummarizeError, match=message):
        summarize._chat([], {})


def test_budget_check(monkeypatch):
    monkeypatch.setattr(config, "LLM_NUM_CTX", 3000)
    monkeypatch.setattr(config, "LLM_MAX_OUTPUT_TOKENS", 1000)
    summarize.check_budget("x" * 4000)  # ~1600 tokens + 1000 output: fits
    with pytest.raises(summarize.SummarizeError, match="Prompt too long"):
        summarize.check_budget("x" * 6000)  # ~2400 + 1000 > 3000


def test_ask_valid_first_time(chat_calls):
    assert summarize.ask("prompt", ChunkExtraction) == EXTRACTION
    assert len(chat_calls) == 1
    assert chat_calls[0]["schema"] == ChunkExtraction.model_json_schema()


def test_ask_retries_once_with_the_error(chat_calls):
    chat_calls.queue.append('{"topics": "not a list"}')
    assert summarize.ask("prompt", ChunkExtraction) == EXTRACTION

    retry = chat_calls[1]["messages"]
    assert retry[1] == {"role": "assistant", "content": '{"topics": "not a list"}'}
    assert "That JSON was invalid" in retry[2]["content"]


def test_ask_gives_up_after_two_invalid_replies(chat_calls):
    chat_calls.queue.extend(["not json", "still not json"])
    with pytest.raises(summarize.SummarizeError, match="invalid output twice"):
        summarize.ask("prompt", ChunkExtraction)


def test_ask_checks_budget_before_calling(chat_calls, monkeypatch):
    monkeypatch.setattr(config, "LLM_NUM_CTX", 100)
    with pytest.raises(summarize.SummarizeError):
        summarize.ask("prompt", ChunkExtraction)
    assert chat_calls == []


# --- the extract step ----------------------------------------------------------

def make_memo(folder, language="es", n_segments=3):
    folder.mkdir()
    (folder / "segments.json").write_text(json.dumps(
        [{"start": i * 10.0, "end": i * 10.0 + 10, "text": f"línea {i}"} for i in range(n_segments)]
    ))
    meta = {"id": "abc"} | ({"language": language} if language else {})
    (folder / "meta.json").write_text(json.dumps(meta))
    return folder


def test_extract_saves_one_result_per_chunk(chat_calls, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHUNK_SECONDS", 20)  # 3 × 10 s segments -> 2 overlapping chunks
    folder = make_memo(tmp_path / "memo")
    progress = []

    results = summarize.extract(folder, lambda done, total: progress.append((done, total)))

    assert results == [EXTRACTION, EXTRACTION]
    assert progress == [(1, 2), (2, 2)]
    assert summarize.is_extracted(folder)
    saved = json.loads((folder / "extractions.json").read_text())
    assert [s["range"] for s in saved] == ["00:00–00:20", "00:10–00:30"]
    assert saved[0]["commitments"][0]["who"] == "Doña Rosa"
    assert not list(folder.glob("*.partial.json"))

    prompt = chat_calls[0]["messages"][0]["content"]
    assert "part 1 of 2" in prompt
    assert "[00:00] línea 0" in prompt
    assert "Spanish (as spoken in Costa Rica)" in prompt


@pytest.mark.parametrize("code, expected", [("pt", "entirely in pt,"), (None, "entirely in the transcript's language,")])
def test_extract_language_fallbacks(chat_calls, tmp_path, code, expected):
    summarize.extract(make_memo(tmp_path / "memo", language=code))
    assert expected in chat_calls[0]["messages"][0]["content"]


def test_extract_without_progress_callback(chat_calls, tmp_path):
    assert summarize.extract(make_memo(tmp_path / "memo")) == [EXTRACTION]
