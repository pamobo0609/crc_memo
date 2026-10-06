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
    "args", [["list"], ["search", "brete"], ["show", "abc"], ["todos"]]
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


# --- sender / date / reprocess ---------------------------------------------------------

@pytest.fixture
def memo(audio_files, memos_dir, tmp_path):
    """A memo processed end to end (fake Whisper + LLM), from a WhatsApp-named file."""
    path = tmp_path / "WhatsApp Audio 2026-09-27 at 08.53.52.ogg"
    path.write_bytes(audio_files[".ogg"].read_bytes())
    assert runner.invoke(app, ["process", str(path)]).exit_code == 0
    (folder,) = memos_dir.iterdir()
    return folder


def test_date_comes_from_the_whatsapp_file_name(memo):
    assert "según el audio del 27 sep 2026" in (memo / "minuta_breve.md").read_text()


def test_process_with_sender_and_date(audio_files, memos_dir):
    result = runner.invoke(app, ["process", str(audio_files[".ogg"]),
                                 "--sender", "Marta", "--date", "2026-10-05"])
    assert result.exit_code == 0, result.output
    (folder,) = memos_dir.iterdir()
    text = (folder / "minuta_breve.md").read_text()
    assert "según el audio del 5 oct 2026" in text and "**Relato de:** Marta" in text


def test_invalid_date_is_rejected(audio_files):
    result = runner.invoke(app, ["process", str(audio_files[".ogg"]), "--date", "5/10/2026"])
    assert result.exit_code == 2
    assert "YYYY-MM-DD" in result.output


def test_reprocess_reruns_from_extract_and_keeps_history(memo, llm_calls):
    before = len(llm_calls)
    result = runner.invoke(app, ["reprocess", memo.name[:4]])  # a unique prefix is enough

    assert result.exit_code == 0, result.output
    output = " ".join(result.output.split())
    assert "Previous outputs saved" in output
    assert f"Rerunning {memo.name} from extract" in output
    assert "Extracted 1 chunks" in output and "Merged" in output
    assert len(llm_calls) == before + 1  # the empty extraction needs no merge/write calls
    (archive,) = (memo / "history").iterdir()
    assert sorted(p.name for p in archive.iterdir()) == [
        "extractions.json", "meta.json", "minuta_breve.md", "minuta_completa.md",
        "minutes.json", "prose.json"]


def test_reprocess_from_merge_keeps_earlier_steps(memo, llm_calls):
    result = runner.invoke(app, ["reprocess", memo.name, "--from", "merge"])
    assert "Already extracted" in result.output
    assert "Merged" in result.output


def test_sender_alone_only_rerenders(memo, llm_calls):
    before = len(llm_calls)
    result = runner.invoke(app, ["reprocess", memo.name, "--sender", "Don Carlos"])

    assert result.exit_code == 0, result.output
    assert "from render" in result.output and "Prose already written" in result.output
    assert len(llm_calls) == before
    assert "**Relato de:** Don Carlos" in (memo / "minuta_breve.md").read_text()
    assert json.loads((memo / "minutes.json").read_text())["source"]["sender"] == "Don Carlos"
    assert json.loads((memo / "meta.json").read_text())["sender"] == "Don Carlos"


def test_reprocess_without_outputs_archives_nothing(memo):
    for name in ["extractions.json", "minutes.json", "prose.json", "minuta_breve.md",
                 "minuta_completa.md"]:
        (memo / name).unlink()
    result = runner.invoke(app, ["reprocess", memo.name])
    assert result.exit_code == 0
    assert "Previous outputs saved" not in result.output
    assert not (memo / "history").exists()


@pytest.mark.parametrize("memo_id, message", [("zzz", "No memo 'zzz'"), ("", "No memo ''")])
def test_reprocess_unknown_memo(memo, memo_id, message):
    result = runner.invoke(app, ["reprocess", memo_id])
    assert result.exit_code == 1
    assert message in result.output


def test_reprocess_ambiguous_prefix(memos_dir):
    for name in ["abc111", "abc222"]:
        (memos_dir / name).mkdir(parents=True)
        (memos_dir / name / "meta.json").write_text("{}")
    result = runner.invoke(app, ["reprocess", "abc"])
    assert result.exit_code == 1
    assert "matches several memos: abc111, abc222" in result.output


def test_reprocess_needs_a_transcript(memos_dir):
    (memos_dir / "abc111").mkdir(parents=True)
    (memos_dir / "abc111" / "meta.json").write_text("{}")
    result = runner.invoke(app, ["reprocess", "abc111"])
    assert result.exit_code == 1
    assert "isn't transcribed yet" in result.output


def test_reprocess_without_memos_dir():
    result = runner.invoke(app, ["reprocess", "abc"])
    assert result.exit_code == 1
    assert "No memo 'abc'" in result.output


def test_warns_when_the_audio_is_not_a_meeting_recap(memo):
    prose = json.loads((memo / "prose.json").read_text()) | {"meeting_recap": False}
    (memo / "prose.json").write_text(json.dumps(prose))
    result = runner.invoke(app, ["reprocess", memo.name, "--from", "render"])
    assert "doesn't seem to retell a meeting" in " ".join(result.output.split())
