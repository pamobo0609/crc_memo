"""Transcribe: audio.wav -> transcript.txt + segments.json, using Whisper on Apple Silicon."""

import json
import re
import wave
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

TRANSCRIPT_NAME = "transcript.txt"
SEGMENTS_NAME = "segments.json"

# Whisper's own repetition test: text that compresses this well is looping.
# Normal Spanish segments measure ~1.3-1.5; a real loop ~8; "bueno, bueno, bueno" ~1.8.
LOOP_COMPRESSION_RATIO = 2.4
REPEAT_RUN = 3  # this many identical lines in a row = Whisper stuck repeating itself


class TranscribeError(Exception):
    """Something the user can act on (Whisper not installed, ...)."""


@dataclass
class Segment:
    start: float  # seconds
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    segments: list[Segment]


@dataclass
class LoopWarning:
    at: float  # seconds
    kind: str  # "repeat" (same line N times in a row) or "loop" (repetitive inside one line)
    text: str  # shortened
    count: int = 1


def _run_whisper(wav: Path, **options) -> dict:
    """The only place that touches mlx_whisper.

    Imported here, not at the top of the file, because mlx-whisper only installs on
    Apple Silicon Macs: the rest of the app (and CI on Linux) must work without it.
    """
    try:
        import mlx_whisper
    except ImportError:
        raise TranscribeError(
            "mlx-whisper is not installed. It needs a Mac with Apple Silicon (run: uv sync)."
        ) from None
    return mlx_whisper.transcribe(str(wav), **options)


def transcribe(
    wav: Path, model: str, language: str | None = None, initial_prompt: str | None = None
) -> Transcript:
    """language=None lets Whisper detect it from the first 30 seconds."""
    result = _run_whisper(
        wav,
        path_or_hf_repo=model,
        language=language,
        initial_prompt=initial_prompt,
        verbose=False,  # False = Whisper's own progress bar; True would print every line
    )
    segments = [
        Segment(round(s["start"], 2), round(s["end"], 2), s["text"].strip())
        for s in result["segments"]
        if s["text"].strip()
    ]
    return Transcript(language=result["language"], segments=segments)


def format_timestamp(seconds: float) -> str:
    """75.4 -> '01:15'; 3725 -> '1:02:05'."""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"


def _normalize(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def _compression_ratio(text: str) -> float:
    data = text.encode()
    return len(data) / len(zlib.compress(data))


def _short(text: str) -> str:
    return text if len(text) <= 60 else text[:57] + "..."


def find_loops(segments: list[Segment]) -> list[LoopWarning]:
    """Spot Whisper's classic long-audio failure: getting stuck repeating itself."""
    warnings = []
    i = 0
    while i < len(segments):
        run = 1
        while (
            i + run < len(segments)
            and _normalize(segments[i + run].text) == _normalize(segments[i].text)
        ):
            run += 1
        if run >= REPEAT_RUN:
            warnings.append(LoopWarning(segments[i].start, "repeat", _short(segments[i].text), run))
        elif _compression_ratio(segments[i].text) > LOOP_COMPRESSION_RATIO:
            warnings.append(LoopWarning(segments[i].start, "loop", _short(segments[i].text)))
        i += run
    return warnings


def audio_duration(wav: Path) -> float:
    """Length in seconds, read from the WAV header."""
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def is_transcribed(folder: Path) -> bool:
    return (folder / TRANSCRIPT_NAME).exists()


def save(transcript: Transcript, folder: Path, stats: dict) -> None:
    """transcript.txt is for reading (one timestamped line per segment, phone-friendly);
    segments.json keeps exact times for chunking in Phase 3; `stats` (model, speed,
    loop warnings) go into meta.json under "transcription".

    transcript.txt is written last: it marks "done", so a crash halfway never
    leaves a memo that looks transcribed but isn't.
    """
    (folder / SEGMENTS_NAME).write_text(
        json.dumps([asdict(s) for s in transcript.segments], indent=1, ensure_ascii=False)
    )

    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["language"] = transcript.language
    meta["transcription"] = stats
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    lines = [f"[{format_timestamp(s.start)}] {s.text}" for s in transcript.segments]
    (folder / TRANSCRIPT_NAME).write_text("\n".join(lines) + "\n")
