"""Summarize: segments.json -> meeting minutes.

3a extract: split the transcript into ~5-minute chunks; the local LLM extracts each to JSON.
3b merge:   combine the chunks and remove duplicates (the LLM only groups; code merges).
Later steps write the reports.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

from crc_memo import config
from crc_memo.schemas import (
    ActionItem,
    ChunkExtraction,
    Merged,
    MergedAction,
    MergedPoint,
    MergePlan,
    Point,
    Tangent,
)
from crc_memo.transcribe import SEGMENTS_NAME, Segment, format_timestamp

EXTRACTIONS_NAME = "extractions.json"
MERGED_NAME = "merged.json"
MERGE_FIELDS = ["decisions", "action_items", "open_questions", "notable"]
VAGUE = {"sin asignar", "sin fecha", ""}  # owner/due values that a later mention can improve
NOT_PARTICIPANTS = {"usted", "speaker", "el speaker", "la speaker", "hablante", "la hablante"}

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


# --- 3b merge -------------------------------------------------------------------

def timestamp_seconds(timestamp: str) -> float:
    """'05:42' -> 342, '1:02:05' -> 3725; anything unparseable sorts last."""
    try:
        parts = [int(p) for p in timestamp.strip().split(":")]
    except ValueError:
        return float("inf")
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def _key(text: str) -> str:
    """Comparison key: lowercase words only, ignoring '(roles)' in parentheses."""
    return " ".join(re.findall(r"\w+", re.sub(r"\(.*?\)", "", text).lower()))


def _union(labels: list[str]) -> list[str]:
    """Ordered union; 'don Carlos' and 'Don Carlos (presidente)' collapse to the longer one."""
    seen: dict[str, str] = {}
    for label in labels:
        key = _key(label)
        if key and (key not in seen or len(label) > len(seen[key])):
            seen[key] = label
    return list(seen.values())


def _range_bounds(range_: str) -> tuple[str, str]:
    """'01:10–01:18' (or with '-') -> ('01:10', '01:18'); a single time is both bounds."""
    start, _, end = range_.replace("-", "–").partition("–")
    return start.strip(), (end or start).strip()


def _merge_tangents(tangents: list[Tangent]) -> list[Tangent]:
    """The same digression seen by two overlapping chunks becomes one (overlapping ranges)."""
    merged: list[Tangent] = []
    for t in sorted(tangents, key=lambda t: timestamp_seconds(_range_bounds(t.range)[0])):
        start, end = _range_bounds(t.range)
        if merged:
            last_start, last_end = _range_bounds(merged[-1].range)
            if timestamp_seconds(start) <= timestamp_seconds(last_end):
                if timestamp_seconds(end) > timestamp_seconds(last_end):
                    merged[-1].range = f"{last_start}–{end}"
                continue
        merged.append(t.model_copy())
    return merged


def _repair(groups: list[list[int]], count: int) -> list[list[int]]:
    """Make the LLM's grouping safe: drop unknown or repeated numbers, add missing ones alone."""
    seen: set[int] = set()
    repaired = []
    for group in groups:
        clean = [i for i in dict.fromkeys(group) if 1 <= i <= count and i not in seen]
        seen.update(clean)
        if clean:
            repaired.append(clean)
    return repaired + [[i] for i in range(1, count + 1) if i not in seen]


def _combine(items: list[Point] | list[ActionItem]) -> MergedPoint | MergedAction:
    """One merged item: earliest wording and quote, every timestamp, most specific owner/due."""
    items = sorted(items, key=lambda i: timestamp_seconds(i.timestamp))
    first = items[0]
    timestamps = list(dict.fromkeys(i.timestamp for i in items))
    if isinstance(first, ActionItem):
        specific = lambda field: next(
            (getattr(i, field) for i in items if getattr(i, field) not in VAGUE), getattr(first, field)
        )
        return MergedAction(timestamps=timestamps, quote=first.quote, task=first.task,
                            owner=specific("owner"), due=specific("due"))
    return MergedPoint(timestamps=timestamps, quote=first.quote, text=first.text)


def _describe(field: str, item: Point | ActionItem) -> str:
    if field == "action_items":
        return f"({item.timestamp}) {item.owner} · {item.due} · {item.task}"
    return f"({item.timestamp}) {item.text}"


def _merge_plan(pools: dict[str, list]) -> MergePlan:
    """Ask the LLM which items are the same fact. Returns number groups (1-based)."""
    sections = []
    for field in MERGE_FIELDS:
        lines = [f"[{n}] {_describe(field, item)}" for n, item in enumerate(pools[field], 1)]
        sections.append(f"## {field}\n" + ("\n".join(lines) or "(none)"))
    return ask(load_prompt("merge", items="\n\n".join(sections)), MergePlan)


def _drop_covered(notable: list[MergedPoint], tangents: list[Tangent],
                  meetings: list) -> list[MergedPoint]:
    """Each fact belongs in one field: drop `notable` items that just repeat a tangent (same
    time range) or the next meeting (same timestamp). The model does this despite the prompt."""
    meeting_times = {m.timestamp for m in meetings}

    def covered(point: MergedPoint) -> bool:
        at = timestamp_seconds(point.timestamps[0])
        in_tangent = any(
            timestamp_seconds(start) <= at <= timestamp_seconds(end)
            for start, end in (_range_bounds(t.range) for t in tangents)
        )
        return in_tangent or point.timestamps[0] in meeting_times

    return [p for p in notable if not covered(p)]


def is_merged(folder: Path) -> bool:
    return (folder / MERGED_NAME).exists()


def merge(folder: Path) -> tuple[Merged, int]:
    """Combine extractions.json into merged.json. Returns (merged, duplicates removed)."""
    chunks = [ChunkExtraction.model_validate(c)
              for c in json.loads((folder / EXTRACTIONS_NAME).read_text())]
    pools = {field: [item for c in chunks for item in getattr(c, field)] for field in MERGE_FIELDS}

    # One chunk: extraction already listed each fact once, so there is nothing to group.
    needs_llm = len(chunks) > 1 and any(len(items) > 1 for items in pools.values())
    plan = _merge_plan(pools) if needs_llm else MergePlan(**{
        field: [{"fact": "", "items": [n]} for n in range(1, len(pools[field]) + 1)]
        for field in MERGE_FIELDS
    })

    merged_items = {}
    for field in MERGE_FIELDS:
        groups = _repair([g.items for g in getattr(plan, field)], len(pools[field]))
        combined = [_combine([pools[field][i - 1] for i in group]) for group in groups]
        merged_items[field] = sorted(combined, key=lambda m: timestamp_seconds(m.timestamps[0]))

    meetings = sorted((m for c in chunks for m in c.next_meeting),
                      key=lambda m: timestamp_seconds(m.timestamp))
    tangents = _merge_tangents([t for c in chunks for t in c.tangents])
    merged_items["notable"] = _drop_covered(merged_items["notable"], tangents, meetings)
    merged = Merged(
        topics=_union([t for c in chunks for t in c.topics]),
        participants=[p for p in _union([p for c in chunks for p in c.participants])
                      if _key(p) not in NOT_PARTICIPANTS],
        tangents=tangents,
        next_meeting=meetings[-1:],  # the last mention is usually the final word
        **merged_items,
    )
    _write_json(folder / MERGED_NAME, merged.model_dump())
    removed = sum(len(pools[f]) - len(merged_items[f]) for f in MERGE_FIELDS)
    return merged, removed
