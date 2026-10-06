"""Summarize: segments.json -> meeting minutes.

3a extract: split the transcript into ~5-minute chunks; the local LLM extracts each to JSON.
3b merge:   combine the chunks into minutes.json, the contract the minuta is rendered from
            (the LLM only groups duplicates; code builds everything else).
Later steps write the reports.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

from crc_memo import config
from crc_memo.schemas import (
    ChunkExtraction,
    Commitment,
    Entry,
    Meeting,
    MergePlan,
    Minutes,
    MinutesCommitment,
    MinutesNextMeeting,
    Point,
    Source,
    Tangent,
    Topic,
    TopicSpan,
)
from crc_memo.transcribe import SEGMENTS_NAME, Segment, format_timestamp

EXTRACTIONS_NAME = "extractions.json"
MINUTES_NAME = "minutes.json"
ENTRY_FIELDS = {"agreements": "A", "pending": "P", "observations": "O"}  # field -> id prefix
GROUPED_FIELDS = ["topics", "agreements", "commitments", "pending", "observations"]
# Values the model writes instead of "" despite the prompt; code turns them into None.
NOT_SAID = {"no se menciona", "no mencionado", "no se dice", "desconocido", "sin fecha",
            "sin asignar", "ninguno", "n a", "none", "unknown"}
# Pronouns for the audio's recipients that the model puts in `who`: they mean for_recipients.
RECIPIENTS = {"usted", "ustedes", "todos", "todos ustedes", "el grupo", "you", "everyone"}
VAGUE_DUE = {"ahorita", "luego", "despues", "pronto", "mas tarde", "cuando pueda", "ya"}
NOT_ATTENDEES = {"usted", "ustedes", "speaker", "el speaker", "la speaker", "hablante",
                 "la hablante", "la persona que habla"}

# Costa Rican money slang -> colones. Applied in code: the model ignored the prompt rule.
MONEY_UNITS = {"teja": 100, "rojo": 1_000, "tucan": 5_000, "palo": 1_000_000}
NUMBER_WORDS = {"un": 1, "una": 1, "uno": 1, "medio": 0.5, "media": 0.5, "dos": 2, "tres": 3,
                "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
                "quince": 15, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
                "cien": 100}
MONEY_RE = re.compile(
    r"\b(?P<n>\d+|" + "|".join(NUMBER_WORDS) + r")\s+(?P<unit>tejas?|rojos?|tuc[aá]n(?:es)?|palos?)\b",
    re.IGNORECASE,
)

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


def normalize_money(text: str) -> str:
    """'cinco rojos' -> '₡5.000', 'medio palo' -> '₡500.000' (Costa Rican format)."""
    def colones(match: re.Match) -> str:
        n = match["n"].lower()
        amount = int(n) if n.isdigit() else NUMBER_WORDS[n]
        unit = match["unit"].lower().replace("á", "a").rstrip("s").removesuffix("e")
        return "₡" + f"{int(amount * MONEY_UNITS[unit]):,}".replace(",", ".")
    return MONEY_RE.sub(colones, text)


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


def _merge_tangents(tangents: list[Tangent]) -> list[Tangent]:
    """The same digression seen by two overlapping chunks becomes one (overlapping ranges)."""
    merged: list[Tangent] = []
    for t in sorted(tangents, key=lambda t: timestamp_seconds(t.start)):
        if merged and timestamp_seconds(t.start) <= timestamp_seconds(merged[-1].end):
            if timestamp_seconds(t.end) > timestamp_seconds(merged[-1].end):
                merged[-1].end = t.end
            continue
        merged.append(t.model_copy(update={"summary": _sentence(t.summary)}))
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


def _timeline(items: list) -> tuple[list, list[str]]:
    """Items in time order, and their distinct timestamps."""
    items = sorted(items, key=lambda i: timestamp_seconds(i.timestamp))
    return items, list(dict.fromkeys(i.timestamp for i in items))


def _plain(text: str) -> str:
    """Lowercase, no accents: for comparing against NOT_SAID / VAGUE_DUE."""
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFD", text.lower())
                                       .encode("ascii", "ignore").decode()))


def _value(text: str, vague: set[str] = frozenset()) -> str | None:
    """A real value, or None for empty / placeholder / vague answers."""
    return None if not text.strip() or _plain(text) in NOT_SAID | vague else text.strip()


def _first(values, vague: set[str] = frozenset()) -> str | None:
    """First real value, or None: unknowns stay None for the renderer to localize."""
    return next((v for v in (_value(v, vague) for v in values) if v), None)


def _sentence(text: str) -> str:
    """Money normalized, first letter capitalized."""
    text = normalize_money(text.strip())
    return text[:1].upper() + text[1:]


def _combine_topics(spans: list[TopicSpan]) -> dict:
    spans = sorted(spans, key=lambda t: timestamp_seconds(t.start))
    return {"title": _sentence(spans[0].title), "start": spans[0].start,
            "end": max((t.end for t in spans), key=timestamp_seconds)}


def _combine_entry(points: list[Point]) -> dict:
    points, timestamps = _timeline(points)
    return {"text": _sentence(points[0].text), "timestamps": timestamps}


def _combine_commitment(items: list[Commitment]) -> dict:
    items, timestamps = _timeline(items)
    return {"what": _sentence(items[0].what), "who": _first((i.who for i in items), RECIPIENTS),
            "for_recipients": any(i.for_recipients or _plain(i.who) in RECIPIENTS for i in items),
            "due": _first((i.due for i in items), VAGUE_DUE), "timestamps": timestamps}


def _describe(field: str, item) -> str:
    if field == "topics":
        return f"({item.start}–{item.end}) {item.title}"
    if field == "commitments":
        who = item.who or ("recipients" if item.for_recipients else "nobody named")
        return f"({item.timestamp}) {who} · {item.due or 'no deadline'} · {item.what}"
    return f"({item.timestamp}) {item.text}"


def _merge_plan(pools: dict[str, list]) -> MergePlan:
    """Ask the LLM which items are the same fact. Returns number groups (1-based)."""
    sections = []
    for field in GROUPED_FIELDS:
        lines = [f"[{n}] {_describe(field, item)}" for n, item in enumerate(pools[field], 1)]
        sections.append(f"## {field}\n" + ("\n".join(lines) or "(none)"))
    return ask(load_prompt("merge", items="\n\n".join(sections)), MergePlan)


def _topic_of(timestamp: str, topics: list[Topic]) -> str | None:
    """The topic being discussed at `timestamp`: the latest topic that started by then."""
    at = timestamp_seconds(timestamp)
    started = [t for t in topics if timestamp_seconds(t.start) <= at]
    return started[-1].id if started else (topics[0].id if topics else None)


def _covered(timestamp: str, tangents: list[Tangent], meeting_times: set[str]) -> bool:
    """An observation that only repeats a tangent (same range) or the next meeting."""
    at = timestamp_seconds(timestamp)
    in_tangent = any(timestamp_seconds(t.start) <= at <= timestamp_seconds(t.end) for t in tangents)
    return in_tangent or timestamp in meeting_times


def _source(folder: Path, segments_end: float) -> Source:
    meta = json.loads((folder / "meta.json").read_text())
    seconds = meta.get("transcription", {}).get("audio_seconds", segments_end)
    return Source(sender=meta.get("sender"), memo_date=meta.get("date"),
                  duration=format_timestamp(seconds), language=meta.get("language", ""))


def is_merged(folder: Path) -> bool:
    return (folder / MINUTES_NAME).exists()


def merge(folder: Path) -> tuple[Minutes, int]:
    """Combine extractions.json into minutes.json. Returns (minutes, duplicates removed)."""
    chunks = [ChunkExtraction.model_validate(c)
              for c in json.loads((folder / EXTRACTIONS_NAME).read_text())]
    pools = {field: [item for c in chunks for item in getattr(c, field)] for field in GROUPED_FIELDS}

    # One chunk: extraction already listed each fact once, so there is nothing to group.
    needs_llm = len(chunks) > 1 and any(len(items) > 1 for items in pools.values())
    plan = _merge_plan(pools) if needs_llm else MergePlan(**{
        field: [{"fact": "", "items": [n]} for n in range(1, len(pools[field]) + 1)]
        for field in GROUPED_FIELDS
    })
    grouped = {
        field: [[pools[field][i - 1] for i in group]
                for group in _repair([g.items for g in getattr(plan, field)], len(pools[field]))]
        for field in GROUPED_FIELDS
    }

    topic_data = sorted((_combine_topics(g) for g in grouped["topics"]),
                        key=lambda t: timestamp_seconds(t["start"]))
    # The model's end times are unreliable: a topic ends where the next one starts.
    for current, following in zip(topic_data, topic_data[1:]):
        current["end"] = following["start"]
    topics = [Topic(id=f"T{n}", **t) for n, t in enumerate(topic_data, 1)]

    tangents = _merge_tangents([t for c in chunks for t in c.tangents])
    meetings = sorted((m for c in chunks for m in c.next_meeting),
                      key=lambda m: timestamp_seconds(m.timestamp))
    meeting_times = {m.timestamp for m in meetings}

    entries = {}
    for field, prefix in ENTRY_FIELDS.items():
        data = sorted((_combine_entry(g) for g in grouped[field]),
                      key=lambda e: timestamp_seconds(e["timestamps"][0]))
        if field == "observations":  # each fact in one field, even when the model repeats it
            data = [e for e in data if not _covered(e["timestamps"][0], tangents, meeting_times)]
        entries[field] = [Entry(id=f"{prefix}{n}", topic=_topic_of(e["timestamps"][0], topics), **e)
                          for n, e in enumerate(data, 1)]
    commitment_data = sorted((_combine_commitment(g) for g in grouped["commitments"]),
                             key=lambda c: timestamp_seconds(c["timestamps"][0]))
    commitments = [MinutesCommitment(id=f"C{n}", topic=_topic_of(c["timestamps"][0], topics), **c)
                   for n, c in enumerate(commitment_data, 1)]
    if topics:  # the last topic runs at least until the last item filed under it
        last_items = [ts for e in [*commitments, *(x for v in entries.values() for x in v)]
                      if e.topic == topics[-1].id for ts in e.timestamps]
        topics[-1].end = max([topics[-1].end, *last_items], key=timestamp_seconds)

    infos = [m for c in chunks for m in c.meeting]
    last = meetings[-1] if meetings else None  # the last mention is usually the final word
    segments = json.loads((folder / SEGMENTS_NAME).read_text())
    minutes = Minutes(
        source=_source(folder, segments[-1]["end"] if segments else 0),
        meeting=Meeting(**{f: _first(getattr(i, f) for i in infos)
                           for f in ["group", "when", "place", "chaired_by"]}),
        attendees=[a for a in _union([a for c in chunks for a in c.attendees])
                   if _key(a) not in NOT_ATTENDEES],
        topics=topics,
        commitments=commitments,
        next_meeting=MinutesNextMeeting(day=_value(last.day), time=_value(last.time),
                                        place=_value(last.place)) if last else None,
        tangents=tangents,
        **entries,
    )
    _write_json(folder / MINUTES_NAME, minutes.model_dump())
    kept = len(topics) + len(commitments) + sum(len(e) for e in entries.values())
    return minutes, sum(len(pool) for pool in pools.values()) - kept
