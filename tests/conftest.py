import subprocess

import pytest

# Encoder per extension. WhatsApp voice notes are Opus inside an .ogg container.
ENCODERS = {".opus": "libopus", ".ogg": "libopus", ".m4a": "aac"}


@pytest.fixture(scope="session")
def audio_files(tmp_path_factory):
    """1 s stereo 48 kHz tone in each format, so conversion has real work to do."""
    folder = tmp_path_factory.mktemp("audio")
    files = {}
    for ext, codec in ENCODERS.items():
        path = folder / f"memo{ext}"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=1", "-ac", "2", "-ar", "48000",
             "-c:a", codec, str(path)],
            check=True,
        )
        files[ext] = path
    return files


@pytest.fixture
def memos_dir(tmp_path):
    return tmp_path / "memos"


@pytest.fixture
def not_audio(tmp_path):
    path = tmp_path / "broken.m4a"
    path.write_bytes(b"this is not audio")
    return path
