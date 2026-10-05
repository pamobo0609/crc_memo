"""Ingest: pick a file, hash it, copy it, convert it to 16kHz mono WAV."""

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ID_LENGTH = 12  # hex chars of the SHA-256; plenty to avoid collisions for personal use
WAV_NAME = "audio.wav"


class IngestError(Exception):
    """Something the user can act on (missing ffmpeg, unreadable audio, ...)."""


@dataclass
class IngestResult:
    memo_id: str
    folder: Path
    skipped: bool  # True when this exact file was already processed


def pick_file() -> Path | None:
    """Open the native macOS file picker. Returns None if the user cancels."""
    result = subprocess.run(
        ["osascript", "-e", 'POSIX path of (choose file with prompt "Choose a voice memo")'],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:  # Cancel makes osascript exit with error -128
        return None
    return Path(result.stdout.strip())


def sha256_of(path: Path) -> str:
    # file_digest reads in chunks, so a 200 MB memo never sits in memory at once.
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def convert_to_wav(src: Path, dst: Path) -> None:
    """16kHz mono 16-bit PCM: the format Whisper models are trained on."""
    if shutil.which("ffmpeg") is None:
        raise IngestError("ffmpeg not found. Install it with: brew install ffmpeg")
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src),
            "-ac", "1",           # mono
            "-ar", "16000",       # 16 kHz
            "-c:a", "pcm_s16le",  # 16-bit WAV
            str(dst),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise IngestError(f"ffmpeg could not convert {src.name}: {result.stderr.strip()}")


def ingest(path: Path, memos_dir: Path) -> IngestResult:
    """Copy `path` into memos_dir/<id>/ and convert it. Skips files seen before."""
    digest = sha256_of(path)
    memo_id = digest[:ID_LENGTH]
    folder = memos_dir / memo_id
    wav = folder / WAV_NAME

    # audio.wav only appears after a successful conversion, so it marks "done".
    if wav.exists():
        return IngestResult(memo_id, folder, skipped=True)

    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, folder / f"original{path.suffix.lower()}")

    # Convert to a temp name, then rename: a crash or ffmpeg error never leaves
    # a half-written audio.wav that would make the next run skip this memo.
    tmp = folder / f"{WAV_NAME}.partial.wav"
    try:
        convert_to_wav(path, tmp)
    except IngestError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.rename(wav)

    meta = {
        "id": memo_id,
        "sha256": digest,
        "source_name": path.name,
        "ingested_at": datetime.now().isoformat(timespec="seconds"),
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return IngestResult(memo_id, folder, skipped=False)
