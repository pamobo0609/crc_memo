"""Ingest: pick a file, hash it, copy it, convert it to 16kHz mono WAV."""

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

ID_LENGTH = 12  # hex chars of the SHA-256; plenty to avoid collisions for personal use
WAV_NAME = "audio.wav"
META_NAME = "meta.json"

# WhatsApp puts the date in exported file names: "WhatsApp Audio 2026-09-27 at 08.53.52.opus"
# (shared from the app) and "PTT-20261005-WA0003.opus" (from the phone's storage).
WHATSAPP_DATES = [
    re.compile(r"WhatsApp (?:Audio|Ptt) (\d{4})-(\d{2})-(\d{2})", re.IGNORECASE),
    re.compile(r"(?:PTT|AUD)-(\d{4})(\d{2})(\d{2})-WA", re.IGNORECASE),
]


class IngestError(Exception):
    """Something the user can act on (missing ffmpeg, unreadable audio, ...)."""


@dataclass
class IngestResult:
    memo_id: str
    folder: Path
    skipped: bool  # True when this exact file was already processed


def date_from_name(name: str) -> str | None:
    """The audio's date ('2026-09-27') from a WhatsApp file name, or None."""
    for pattern in WHATSAPP_DATES:
        if match := pattern.search(name):
            try:
                return date(*map(int, match.groups())).isoformat()
            except ValueError:  # e.g. month 13: not a real date
                return None
    return None


def update_meta(folder: Path, **values) -> dict:
    """Set keys in the memo's meta.json; returns the updated meta."""
    path = folder / META_NAME
    meta = json.loads(path.read_text()) | values
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return meta


def find_memo(memos_dir: Path, memo_id: str) -> Path:
    """The folder of memo `memo_id`, which may be a unique prefix ("a8d8")."""
    matches = sorted(memos_dir.glob(f"{memo_id}*")) if memo_id and memos_dir.is_dir() else []
    matches = [m for m in matches if (m / META_NAME).exists()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise IngestError(f"No memo {memo_id!r} in {memos_dir}")
    raise IngestError(f"{memo_id!r} matches several memos: {', '.join(m.name for m in matches)}")


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
