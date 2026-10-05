"""Real Whisper on synthetic Spanish speech — opt-in, never part of the default run.

    uv run pytest -m integration --no-cov

Needs macOS (`say` for speech, mlx-whisper for the model) and downloads the model on
first use (~1.6 GB, free). It guards transcription *quality*, which the unit tests
can't: they fake Whisper.
"""

import os
import platform
import re
import shutil
import subprocess

import pytest

from crc_memo import config, ingest, transcribe

pytestmark = pytest.mark.integration

VOICE = "Paulina"  # Mexican Spanish, the closest macOS voice to Costa Rican
SCRIPT = (
    "Diay mae, le cuento rapidito del brete. "
    "Me jalé una torta con la cotización, entonces ocupo los diseños antes del viernes. "
    "El chunche de la oficina se volvió a pegar, qué salado. Pura vida, hablamos ahorita."
)
# Word error rate limit. Measured on this script (deterministic across runs):
#   large-v3-turbo 5.6% (2/36 words: "Diay mae" -> "Diaymei")
#   tiny          13.9% (5/36: "de Jaime", "rápido", "jale", "ocupó" ...)
# 10% allows at most 3 wrong words, so a downgrade like tiny fails.
MAX_WER = 0.10


def words(text: str) -> list[str]:
    """Lowercase, no punctuation. Accents are kept: "ocupo" (I need) != "ocupó" (he occupied)."""
    return re.findall(r"[\wáéíóúüñ]+", text.lower())


def word_error_rate(reference: str, hypothesis: str) -> float:
    """(substitutions + deletions + insertions) / reference words — edit distance over words."""
    ref, hyp = words(reference), words(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        current = [i]
        for j, hyp_word in enumerate(hyp, 1):
            current.append(min(
                previous[j] + 1,                            # deletion
                current[j - 1] + 1,                         # insertion
                previous[j - 1] + (ref_word != hyp_word),   # substitution (or match)
            ))
        previous = current
    return previous[-1] / len(ref)


def test_word_error_rate():
    assert word_error_rate("ocupo los diseños", "ocupo los diseños") == 0
    assert word_error_rate("ocupo los diseños", "ocupó los diseños") == 1 / 3
    assert word_error_rate("diay mae le cuento", "diaymei le cuento") == 2 / 4


def missing(reason: str) -> None:
    """Skip locally; fail in CI, where a skip would be a green run that tested nothing."""
    if os.environ.get("CRC_MEMO_REQUIRE_INTEGRATION"):
        pytest.fail(f"integration prerequisite missing: {reason}")
    pytest.skip(reason)


@pytest.fixture
def spanish_memo(tmp_path):
    if platform.system() != "Darwin" or not shutil.which("say"):
        missing("needs macOS `say`")
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    if not any(line.startswith(VOICE + " ") for line in voices.splitlines()):
        missing(f"macOS voice {VOICE!r} is not installed")
    path = tmp_path / "memo.m4a"
    subprocess.run(
        ["say", "-v", VOICE, "-o", str(path), "--data-format=aac", SCRIPT], check=True
    )
    return path


def test_real_whisper_transcribes_costa_rican_spanish(spanish_memo, tmp_path):
    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        missing("mlx-whisper is not installed (Apple Silicon only)")

    folder = ingest.ingest(spanish_memo, tmp_path / "memos").folder
    result = transcribe.transcribe(folder / ingest.WAV_NAME, config.WHISPER_MODEL)
    transcribe.save(result, folder)

    text = " ".join(s.text for s in result.segments)
    assert result.language == "es"
    wer = word_error_rate(SCRIPT, text)
    assert wer <= MAX_WER, f"word error rate {wer:.1%} > {MAX_WER:.0%}\n---\n{text}"
