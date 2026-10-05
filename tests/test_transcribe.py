import json
import sys
from types import SimpleNamespace

import pytest

from crc_memo import ingest, transcribe

FAKE_RESULT = {
    "language": "es",
    "segments": [
        {"start": 0.0, "end": 4.123, "text": " Diay mae, le cuento del brete."},
        {"start": 4.123, "end": 5.0, "text": "   "},  # silence Whisper sometimes emits
        {"start": 75.456, "end": 80.0, "text": " Ocupo los diseños el viernes."},
    ],
}


@pytest.fixture
def whisper_calls(monkeypatch):
    """Replace Whisper with a canned result and record how it was called."""
    calls = []

    def fake(wav, **options):
        calls.append((wav, options))
        return FAKE_RESULT

    monkeypatch.setattr(transcribe, "_run_whisper", fake)
    return calls


@pytest.fixture
def memo_folder(audio_files, memos_dir):
    return ingest.ingest(audio_files[".m4a"], memos_dir).folder


def test_transcribe_maps_segments(whisper_calls, tmp_path):
    result = transcribe.transcribe(tmp_path / "audio.wav", "some/model")

    assert result.language == "es"
    assert [s.text for s in result.segments] == [
        "Diay mae, le cuento del brete.",
        "Ocupo los diseños el viernes.",
    ]
    assert result.segments[0].end == 4.12
    assert result.segments[1].start == 75.46


def test_transcribe_passes_options(whisper_calls, tmp_path):
    transcribe.transcribe(tmp_path / "audio.wav", "some/model", "es", "Brete, chunche.")

    _, options = whisper_calls[0]
    assert options == {
        "path_or_hf_repo": "some/model",
        "language": "es",
        "initial_prompt": "Brete, chunche.",
        "verbose": False,
    }


def test_language_defaults_to_auto_detect(whisper_calls, tmp_path):
    transcribe.transcribe(tmp_path / "audio.wav", "some/model")
    assert whisper_calls[0][1]["language"] is None


def test_run_whisper_calls_mlx(monkeypatch, tmp_path):
    seen = {}

    def fake_transcribe(path, **options):
        seen.update(path=path, **options)
        return FAKE_RESULT

    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=fake_transcribe))
    assert transcribe._run_whisper(tmp_path / "a.wav", language="es") is FAKE_RESULT
    assert seen == {"path": str(tmp_path / "a.wav"), "language": "es"}


def test_run_whisper_without_mlx(monkeypatch, tmp_path):
    # None in sys.modules makes `import mlx_whisper` raise ImportError — as on Linux/CI.
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)
    with pytest.raises(transcribe.TranscribeError, match="Apple Silicon"):
        transcribe._run_whisper(tmp_path / "a.wav")


@pytest.mark.parametrize(
    "seconds, expected",
    [(0, "00:00"), (75.4, "01:15"), (3599.9, "59:59"), (3725, "1:02:05")],
)
def test_format_timestamp(seconds, expected):
    assert transcribe.format_timestamp(seconds) == expected


def test_audio_duration(memo_folder):
    assert transcribe.audio_duration(memo_folder / ingest.WAV_NAME) == pytest.approx(1.0, abs=0.1)


def test_save_writes_transcript_segments_and_language(whisper_calls, memo_folder):
    result = transcribe.transcribe(memo_folder / ingest.WAV_NAME, "some/model")
    assert not transcribe.is_transcribed(memo_folder)

    transcribe.save(result, memo_folder, {"speed": 16.0, "warnings": []})

    assert transcribe.is_transcribed(memo_folder)
    assert (memo_folder / "transcript.txt").read_text() == (
        "[00:00] Diay mae, le cuento del brete.\n"
        "[01:15] Ocupo los diseños el viernes.\n"
    )
    segments = json.loads((memo_folder / "segments.json").read_text())
    assert segments[1] == {"start": 75.46, "end": 80.0, "text": "Ocupo los diseños el viernes."}
    meta = json.loads((memo_folder / "meta.json").read_text())
    assert meta["language"] == "es"
    assert meta["transcription"] == {"speed": 16.0, "warnings": []}
    assert meta["source_name"] == "memo.m4a"  # existing fields are kept


def test_failed_save_does_not_look_transcribed(whisper_calls, memo_folder):
    result = transcribe.transcribe(memo_folder / ingest.WAV_NAME, "some/model")
    (memo_folder / "meta.json").unlink()  # make saving fail halfway

    with pytest.raises(FileNotFoundError):
        transcribe.save(result, memo_folder, {})
    assert not transcribe.is_transcribed(memo_folder)


def seg(start, text):
    return transcribe.Segment(start, start + 5, text)


CLEAN = [
    seg(0, "Diay mae, le cuento rapidito cómo está el brete con lo del sitio web."),
    seg(5, "Bueno, bueno, bueno. Eso lo vemos en enero."),  # natural repetition: fine
    seg(10, "Pura vida, hablamos ahorita."),
]


def test_find_loops_clean_transcript():
    assert transcribe.find_loops(CLEAN) == []


def test_find_loops_repeated_lines():
    stuck = [seg(0, "Hola."), seg(750, "Gracias por ver el video."), seg(755, "gracias por ver el video"),
             seg(760, "Gracias, por ver el video!"), seg(765, "Pura vida.")]
    assert transcribe.find_loops(stuck) == [
        transcribe.LoopWarning(750, "repeat", "Gracias por ver el video.", 3)
    ]


def test_find_loops_two_repeats_is_not_a_loop():
    assert transcribe.find_loops([seg(0, "Sí."), seg(5, "Sí."), seg(10, "Listo.")]) == []


def test_find_loops_inside_one_segment():
    looping = seg(90, "y entonces le dije que sí, " * 12)
    (warning,) = transcribe.find_loops(CLEAN + [looping])
    assert (warning.at, warning.kind, warning.count) == (90, "loop", 1)
    assert len(warning.text) == 60 and warning.text.endswith("...")
