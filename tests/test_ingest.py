import json
import subprocess
import wave
from pathlib import Path

import pytest

from crc_memo import ingest


@pytest.mark.parametrize("ext", [".opus", ".ogg", ".m4a"])
def test_ingest_produces_16k_mono_wav(audio_files, memos_dir, ext):
    result = ingest.ingest(audio_files[ext], memos_dir)

    assert not result.skipped
    assert result.folder == memos_dir / result.memo_id
    with wave.open(str(result.folder / "audio.wav")) as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 16000
        assert w.getsampwidth() == 2  # 16-bit
        assert w.getnframes() == pytest.approx(16000, abs=1000)  # ~1 second


def test_ingest_keeps_original_and_metadata(audio_files, memos_dir):
    src = audio_files[".m4a"]
    result = ingest.ingest(src, memos_dir)

    assert (result.folder / "original.m4a").read_bytes() == src.read_bytes()
    meta = json.loads((result.folder / "meta.json").read_text())
    assert meta["id"] == result.memo_id
    assert meta["sha256"].startswith(result.memo_id)
    assert meta["source_name"] == "memo.m4a"
    assert not list(result.folder.glob("*.partial*"))


def test_memo_id_is_hash_prefix(audio_files, memos_dir):
    src = audio_files[".opus"]
    result = ingest.ingest(src, memos_dir)
    assert result.memo_id == ingest.sha256_of(src)[: ingest.ID_LENGTH]


def test_original_extension_is_lowercased(audio_files, memos_dir, tmp_path):
    upper = tmp_path / "MEMO.M4A"
    upper.write_bytes(audio_files[".m4a"].read_bytes())
    result = ingest.ingest(upper, memos_dir)
    assert (result.folder / "original.m4a").exists()


def test_second_run_skips_without_converting(audio_files, memos_dir, monkeypatch):
    first = ingest.ingest(audio_files[".ogg"], memos_dir)

    def fail(*args):
        raise AssertionError("should not convert again")

    monkeypatch.setattr(ingest, "convert_to_wav", fail)
    second = ingest.ingest(audio_files[".ogg"], memos_dir)

    assert second.skipped
    assert second.memo_id == first.memo_id


def test_failed_conversion_is_not_marked_done(not_audio, memos_dir):
    with pytest.raises(ingest.IngestError, match="could not convert broken.m4a"):
        ingest.ingest(not_audio, memos_dir)

    folder = memos_dir / ingest.sha256_of(not_audio)[: ingest.ID_LENGTH]
    assert not (folder / "audio.wav").exists()
    assert not list(folder.glob("*.partial*"))
    # A retry runs the conversion again instead of skipping.
    with pytest.raises(ingest.IngestError):
        ingest.ingest(not_audio, memos_dir)


def test_missing_ffmpeg(audio_files, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest.shutil, "which", lambda name: None)
    with pytest.raises(ingest.IngestError, match="brew install ffmpeg"):
        ingest.convert_to_wav(audio_files[".m4a"], tmp_path / "out.wav")


def test_sha256_of(tmp_path):
    path = tmp_path / "hello.txt"
    path.write_bytes(b"hello")
    assert ingest.sha256_of(path) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def _fake_osascript(monkeypatch, returncode, stdout=""):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(ingest.subprocess, "run", run)
    return calls


def test_pick_file_returns_chosen_path(monkeypatch):
    calls = _fake_osascript(monkeypatch, 0, "/Users/me/Downloads/nota de voz.ogg\n")
    assert ingest.pick_file() == Path("/Users/me/Downloads/nota de voz.ogg")
    assert calls[0][0] == "osascript"


def test_pick_file_cancel_returns_none(monkeypatch):
    _fake_osascript(monkeypatch, 1)
    assert ingest.pick_file() is None


@pytest.mark.parametrize("name, expected", [
    ("WhatsApp Audio 2026-09-27 at 08.53.52.opus", "2026-09-27"),
    ("whatsapp ptt 2026-01-02 at 10.00.00.ogg", "2026-01-02"),
    ("PTT-20261005-WA0003.opus", "2026-10-05"),
    ("AUD-20250131-WA0001.m4a", "2025-01-31"),
    ("PTT-20261305-WA0003.opus", None),  # month 13
    ("memo_tico.m4a", None),
    ("", None),
])
def test_date_from_name(name, expected):
    assert ingest.date_from_name(name) == expected


def test_update_meta(tmp_path):
    (tmp_path / "meta.json").write_text('{"id": "x", "sender": "old"}')
    assert ingest.update_meta(tmp_path, sender="Marta") == {"id": "x", "sender": "Marta"}
    assert json.loads((tmp_path / "meta.json").read_text())["sender"] == "Marta"
