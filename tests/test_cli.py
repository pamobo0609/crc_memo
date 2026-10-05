import pytest
from typer.testing import CliRunner

from crc_memo import config, ingest
from crc_memo.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_data(memos_dir, monkeypatch):
    """Never touch the real data/ folder from tests."""
    monkeypatch.setattr(config, "MEMOS_DIR", memos_dir)


def test_help_lists_all_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["process", "list", "search", "show", "todos", "reprocess"]:
        assert command in result.output


def test_process_ingests_then_skips(audio_files, memos_dir):
    path = str(audio_files[".ogg"])

    first = runner.invoke(app, ["process", path])
    assert first.exit_code == 0
    assert "Ingested" in first.output
    assert len(list(memos_dir.glob("*/audio.wav"))) == 1

    second = runner.invoke(app, ["process", path])
    assert second.exit_code == 0
    assert "Already processed" in second.output


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
