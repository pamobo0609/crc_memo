import json

import pytest
from typer.testing import CliRunner

from crc_memo import config, ingest, transcribe
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
