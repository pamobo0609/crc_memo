"""Summarize: segments.json -> meeting minutes.

Step 3a (this file so far): split the transcript into ~5-minute chunks and extract each one
to structured JSON with the local LLM. Later steps merge the chunks and write the reports.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

from crc_memo import config
from crc_memo.schemas import ChunkExtraction
from crc_memo.transcribe import SEGMENTS_NAME, Segment, format_timestamp

EXTRACTIONS_NAME = "extractions.json"

# Conservative chars-per-token for the budget check (Spanish speech measured ~3.3; lower is safer).
CHARS_PER_TOKEN = 2.5
LANGUAGE_NAMES = {"es": "Spanish (as spoken in Costa Rica)", "en": "English"}

Model = TypeVar("Model", bound=BaseModel)


class SummarizeError(Exception):
    """Something the user can act on (Ollama not running, model missing, ...)."""


@dataclass
class Chunk:
    segments: list[Segment]

    @property
    def range(self) -> str:
        return f"{format_timestamp(self.segments[0].start)}–{format_timestamp(self.segments[-1].end)}"

    @property
    def text(self) -> str:
        return "\n".join(f"[{format_timestamp(s.start)}] {s.text}" for s in self.segments)


def chunk_segments(
    segments: list[Segment], seconds: float | None = None, overlap: int = 1
) -> list[Chunk]:
    """~`seconds`-long chunks (default: config.CHUNK_SECONDS) split on segment boundaries.
    The last `overlap` segments of a chunk repeat at the start of the next, so nothing said
    across a cut is lost (the merge step removes the duplicates)."""
    # Read the setting at call time: a default of `config.CHUNK_SECONDS` in the signature
    # would be frozen when the module is imported.
    seconds = config.CHUNK_SECONDS if seconds is None else seconds
    chunks = []
    i = 0
    while i < len(segments):
        start = segments[i].start
        j = i + 1  # a chunk always has at least one segment, even a very long one
        while j < len(segments) and segments[j].end - start <= seconds:
            j += 1
        chunks.append(Chunk(segments[i:j]))
        if j == len(segments):
            break
        i = max(j - overlap, i + 1)
    return chunks


def load_prompt(prompt_name: str, /, **values) -> str:
    """Fill `{key}` placeholders by plain replacement, so `{` in prompt text is safe.
    `prompt_name` is positional-only, so any placeholder name (even "name") can be filled."""
    text = (config.PROMPTS_DIR / f"{prompt_name}.md").read_text()
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def glossary_notes(text: str) -> str:
    """Regional-term notes for this text. Empty until Phase 3.5 shows they help."""
    return ""


def _chat(messages: list[dict], schema: dict) -> ollama.ChatResponse:
    """The only place that talks to Ollama (tests replace this function)."""
    try:
        return ollama.chat(
            model=config.LLM_MODEL,
            messages=messages,
            format=schema,  # constrained decoding: the reply can only be JSON of this shape
            think=False,  # Qwen3 "thinks" by default; not worth ~40 s per call for extraction
            options={
                "num_ctx": config.LLM_NUM_CTX,
                "num_predict": config.LLM_MAX_OUTPUT_TOKENS,
                "temperature": config.LLM_TEMPERATURE,
                "seed": config.LLM_SEED,
            },
        )
    except ConnectionError:
        raise SummarizeError("Can't reach Ollama. Start it with: brew services start ollama") from None
    except ollama.ResponseError as e:
        if e.status_code == 404:
            raise SummarizeError(
                f"Model {config.LLM_MODEL} isn't downloaded. Run: ollama pull {config.LLM_MODEL}"
            ) from None
        raise SummarizeError(f"Ollama error: {e.error}") from None


def check_budget(prompt: str) -> None:
    """Refuse prompts that might not fit: Ollama would silently drop the start of them."""
    estimated = len(prompt) / CHARS_PER_TOKEN
    if estimated + config.LLM_MAX_OUTPUT_TOKENS > config.LLM_NUM_CTX:
        raise SummarizeError(
            f"Prompt too long (~{estimated:.0f} tokens) for LLM_NUM_CTX={config.LLM_NUM_CTX}. "
            "Lower CHUNK_SECONDS or raise LLM_NUM_CTX."
        )


def ask(prompt: str, model: type[Model]) -> Model:
    """One LLM call returning a validated `model`. On invalid output, retry once with the
    error in the conversation: at temperature 0 a plain retry would repeat the same answer."""
    check_budget(prompt)
    schema = model.model_json_schema()
    messages = [{"role": "user", "content": prompt}]
    reply = _chat(messages, schema)
    try:
        return model.model_validate_json(reply.message.content)
    except ValidationError as first:
        messages += [
            {"role": "assistant", "content": reply.message.content},
            {"role": "user", "content": f"That JSON was invalid:\n{first}\nReturn corrected JSON only."},
        ]
    reply = _chat(messages, schema)
    try:
        return model.model_validate_json(reply.message.content)
    except ValidationError as second:
        raise SummarizeError(
            f"The model returned invalid output twice ({second.error_count()} errors)."
        ) from None


def _write_json(path: Path, data) -> None:
    """Write via a temp file + rename, so a crash never leaves a half-written file."""
    tmp = path.with_suffix(".partial.json")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.rename(path)


def is_extracted(folder: Path) -> bool:
    return (folder / EXTRACTIONS_NAME).exists()


def extract(
    folder: Path, on_progress: Callable[[int, int], None] = lambda done, total: None
) -> list[ChunkExtraction]:
    """Chunk the transcript and extract each chunk; saves extractions.json."""
    segments = [Segment(**s) for s in json.loads((folder / SEGMENTS_NAME).read_text())]
    code = json.loads((folder / "meta.json").read_text()).get("language", "")
    language = LANGUAGE_NAMES.get(code, code or "the transcript's language")

    chunks = chunk_segments(segments)
    results = []
    for n, chunk in enumerate(chunks, 1):
        prompt = load_prompt(
            "extract",
            part=n,
            parts=len(chunks),
            range=chunk.range,
            language=language,
            glossary=glossary_notes(chunk.text),
            transcript=chunk.text,
        )
        results.append(ask(prompt, ChunkExtraction))
        on_progress(n, len(chunks))

    _write_json(
        folder / EXTRACTIONS_NAME,
        [{"range": c.range, **r.model_dump()} for c, r in zip(chunks, results)],
    )
    return results
