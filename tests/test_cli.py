import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from crc_memo import config, ingest, summarize, transcribe
from crc_memo.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_data(memos_dir, monkeypatch):
    """Never touch the real data/ folder from tests."""
    monkeypatch.setattr(config, "MEMOS_DIR", memos_dir)


@pytest.fixture(autouse=True)
def whisper_calls(monkeypatch):
    """Fake Whisper for every CLI test: offline, fast, works on Linux."""
    calls = []

    def fake(wav, **options):
        calls.append(options)
        return {"language": "es", "segments": [{"start": 0.0, "end": 1.0, "text": " Pura vida."}]}

    monkeypatch.setattr(transcribe, "_run_whisper", fake)
    return calls


EMPTY_EXTRACTION = (
    '{"meeting": [], "topics": [], "attendees": [], "agreements": [], "commitments": [], '
    '"pending": [], "observations": [], "tangents": [], "next_meeting": []}'
)


@pytest.fixture(autouse=True)
def llm_calls(monkeypatch):
    """Fake Ollama for every CLI test."""
    calls = []

    def fake(messages, schema):
        calls.append(messages)
        return SimpleNamespace(message=SimpleNamespace(content=EMPTY_EXTRACTION))

    monkeypatch.setattr(summarize, "_chat", fake)
    return calls


def test_help_lists_all_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["process", "list", "search", "show", "todos", "reprocess"]:
        assert command in result.output


def test_process_ingests_and_transcribes(audio_files, memos_dir):
    result = runner.invoke(app, ["process", str(audio_files[".ogg"])])

    assert result.exit_code == 0, result.output
    assert "Ingested" in result.output
    assert "Transcribed 00:01 of audio in" in result.output
    assert "× real time" in result.output
    assert "language es" in result.output
    assert "possible Whisper loop" not in result.output
    (folder,) = memos_dir.iterdir()
    assert (folder / "transcript.txt").read_text() == "[00:00] Pura vida.\n"
    stats = json.loads((folder / "meta.json").read_text())["transcription"]
    assert stats["model"] == config.WHISPER_MODEL
    assert stats["audio_seconds"] == pytest.approx(1.0, abs=0.1)
    assert stats["warnings"] == []
    assert "Extracted 1 chunks" in result.output
    assert (folder / "extractions.json").exists()
    assert "Merged" in result.output
    assert (folder / "minutes.json").exists()
    assert "Wrote the prose" in result.output
    assert (folder / "minuta_breve.md").read_text().startswith("# Minuta — Reunión")
    assert (folder / "minuta_completa.md").exists()


def test_process_warns_about_loops(audio_files, monkeypatch):
    stuck = [{"start": 750.0 + i, "end": 751.0 + i, "text": " [música] Gracias."} for i in range(4)]
    monkeypatch.setattr(
        transcribe, "_run_whisper", lambda wav, **o: {"language": "es", "segments": stuck}
    )
    result = runner.invoke(app, ["process", str(audio_files[".m4a"])])

    assert result.exit_code == 0
    assert "possible Whisper loop at [12:30] (×4): «[música] Gracias.»" in result.output
    assert "if loops are common" in result.output


def test_process_twice_skips_both_steps(audio_files, whisper_calls):
    path = str(audio_files[".ogg"])
    runner.invoke(app, ["process", path])

    second = runner.invoke(app, ["process", path])
    assert second.exit_code == 0
    assert "Already ingested" in second.output
    assert "Already transcribed" in second.output
    assert "Already extracted" in second.output
    assert "Already merged" in second.output
    assert "Prose already written" in second.output
    assert "Minuta → " in second.output  # rendering always reruns
    assert len(whisper_calls) == 1  # Whisper ran only the first time


def test_process_lang_option(audio_files, whisper_calls):
    result = runner.invoke(app, ["process", str(audio_files[".m4a"]), "--lang", "es"])
    assert result.exit_code == 0
    assert whisper_calls[0]["language"] == "es"


def test_process_reports_transcription_error(audio_files, monkeypatch):
    def broken(wav, **options):
        raise transcribe.TranscribeError("mlx-whisper is not installed")

    monkeypatch.setattr(transcribe, "_run_whisper", broken)
    result = runner.invoke(app, ["process", str(audio_files[".m4a"])])
    assert result.exit_code == 1
    assert "mlx-whisper is not installed" in result.output


def test_process_without_path_uses_picker(audio_files, memos_dir, monkeypatch):
    monkeypatch.setattr(ingest, "pick_file", lambda: audio_files[".m4a"])
    result = runner.invoke(app, ["process"])
    assert result.exit_code == 0
    assert "Ingested" in result.output


def test_process_picker_cancelled(monkeypatch):
    monkeypatch.setattr(ingest, "pick_file", lambda: None)
    result = runner.invoke(app, ["process"])
    assert result.exit_code == 1
    assert "No file chosen" in result.output


def test_process_reports_conversion_error(not_audio):
    result = runner.invoke(app, ["process", str(not_audio)])
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_process_rejects_missing_file(tmp_path):
    result = runner.invoke(app, ["process", str(tmp_path / "nope.m4a")])
    assert result.exit_code == 2  # typer's usage error


@pytest.mark.parametrize(
    "args", [["list"], ["search", "brete"], ["show", "abc"], ["todos"], ["reprocess", "abc"]]
)
def test_unimplemented_commands_say_so(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert "Not implemented yet" in result.output


def test_process_reports_llm_error(audio_files, monkeypatch):
    def down(messages, schema):
        raise summarize.SummarizeError("Can't reach Ollama. Start it with: brew services start ollama")

    monkeypatch.setattr(summarize, "_chat", down)
    result = runner.invoke(app, ["process", str(audio_files[".m4a"])])
    assert result.exit_code == 1
    assert "brew services start ollama" in result.output


def test_process_prints_llm_stats(audio_files, monkeypatch):
    def fake(messages, schema):
        return SimpleNamespace(
            message=SimpleNamespace(content=EMPTY_EXTRACTION), done_reason="length",
            prompt_eval_count=1234, prompt_eval_duration=2_000_000_000,
            eval_count=120, eval_duration=10_000_000_000, load_duration=4_000_000_000,
        )

    monkeypatch.setattr(summarize, "_chat", fake)
    result = runner.invoke(app, ["process", str(audio_files[".ogg"])])

    assert result.exit_code == 0, result.output
    output = " ".join(result.output.split())  # rich wraps long lines at the terminal width
    assert ("1 LLM calls · read 1,234 tokens in 00:02 · wrote 120 tokens in 00:10 "
            "(12.0 tokens/s) · model load 00:04") in output
    assert "⚠ 1 replies hit the output limit" in output


def test_process_hides_tiny_model_load(audio_files, monkeypatch):
    def fake(messages, schema):
        return SimpleNamespace(message=SimpleNamespace(content=EMPTY_EXTRACTION),
                               eval_count=10, eval_duration=1_000_000_000, load_duration=50_000_000)

    monkeypatch.setattr(summarize, "_chat", fake)
    result = runner.invoke(app, ["process", str(audio_files[".ogg"])])
    assert "(10.0 tokens/s)" in " ".join(result.output.split())
    assert "model load" not in result.output
    assert "output limit" not in result.output
