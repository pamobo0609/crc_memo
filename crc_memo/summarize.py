"""Summarize: segments.json -> meeting minutes.

3a extract: split the transcript into ~5-minute chunks; the local LLM extracts each to JSON.
3b merge:   combine the chunks into minutes.json, the contract the minuta is rendered from
            (the LLM only groups duplicates; code builds everything else).
3c write:   the LLM writes the prose: a "desarrollo" per topic from that topic's transcript,
            then a title + resumen from those (never from the raw transcript). prose.json.
            Rendering the minuta from minutes.json + prose.json is output.py's job.
"""

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

from crc_memo import config, ingest
from crc_memo.schemas import (
    ChunkExtraction,
    Commitment,
    Development,
    Entry,
    Meeting,
    MergePlan,
    NextMeeting,
    Minutes,
    MinutesCommitment,
    MinutesNextMeeting,
    Overview,
    OwnerCheck,
    Point,
    Prose,
    Source,
    Tangent,
    Topic,
    TopicSpan,
)
from crc_memo.transcribe import SEGMENTS_NAME, Segment, format_timestamp

EXTRACTIONS_NAME = "extractions.json"
MINUTES_NAME = "minutes.json"
PROSE_NAME = "prose.json"
ENTRY_FIELDS = {"agreements": "A", "pending": "P", "observations": "O"}  # field -> id prefix
GROUPED_FIELDS = ["topics", "agreements", "commitments", "pending", "observations"]
# Values the model writes instead of "" despite the prompt; code turns them into None.
NOT_SAID = {"no se dice", "desconocido", "sin fecha", "sin asignar", "ninguno", "n a", "none",
            "unknown"}
# ...and sentences built around a placeholder ("No se menciona quién…", "no especificado").
NOT_SAID_PREFIXES = ("no se menciona", "no mencionad", "no se especifica", "no especificad",
                     "not mentioned", "not specified")
# Pronouns the model puts in `who` instead of choosing the owner: they mean that owner.
RECIPIENTS = {"usted", "ustedes", "todos", "todos ustedes", "el grupo", "you", "everyone"}
SPEAKER = {"yo", "speaker", "el speaker", "la speaker", "hablante", "la hablante",
           "la persona que habla", "el que habla", "la que habla"}
# How prompts name an owner role (prompts are in English).
OWNER_NAMES = {"speaker": "the person speaking", "recipients": "the people receiving the audio"}
VAGUE_DUE = {"ahorita", "luego", "despues", "pronto", "mas tarde", "cuando pueda", "ya"}
NOT_ATTENDEES = {"usted", "ustedes"} | SPEAKER

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

# Qwen occasionally slips a Chinese character into Spanish text ("participación de圳").
# Memos are Spanish or English, so these are always noise.
CJK_RE = re.compile(r"[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")

# Conservative chars-per-token for the budget check (Spanish speech measured ~3.3; lower is safer).
CHARS_PER_TOKEN = 2.5
LANGUAGE_NAMES = {"es": "Spanish (as spoken in Costa Rica)", "en": "English"}

Model = TypeVar("Model", bound=BaseModel)


class SummarizeError(Exception):
    """Something the user can act on (Ollama not running, model missing, ...)."""


@dataclass
class LLMStats:
    """Totals over one step's LLM calls, from the counters Ollama returns with every reply.
    Reading the prompt and writing the answer are timed separately: on a local model writing
    is usually the slow part, so this shows where a step's time (and fan noise) goes."""
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    prompt_seconds: float = 0.0
    output_seconds: float = 0.0
    load_seconds: float = 0.0  # loading the model into memory (first call after a while)
    truncated: int = 0  # replies cut off by LLM_MAX_OUTPUT_TOKENS

    def add(self, reply) -> None:
        # Counters can be missing (None), e.g. on replies served from cache.
        count = lambda field: getattr(reply, field, None) or 0
        self.calls += 1
        self.prompt_tokens += count("prompt_eval_count")
        self.output_tokens += count("eval_count")
        self.prompt_seconds += count("prompt_eval_duration") / 1e9  # Ollama reports nanoseconds
        self.output_seconds += count("eval_duration") / 1e9
        self.load_seconds += count("load_duration") / 1e9
        self.truncated += getattr(reply, "done_reason", None) == "length"

    @property
    def output_speed(self) -> float:
        """Tokens written per second."""
        return self.output_tokens / self.output_seconds if self.output_seconds else 0.0

    def to_dict(self) -> dict:
        data = {k: round(v, 1) if isinstance(v, float) else v for k, v in asdict(self).items()}
        return data | {"output_speed": round(self.output_speed, 1)}


def save_stats(folder: Path, step: str, stats: LLMStats) -> None:
    """Record a step's LLM stats in meta.json under "llm", next to the transcription stats."""
    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta.setdefault("llm", {})[step] = {"model": config.LLM_MODEL, **stats.to_dict()}
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))


@dataclass
class Chunk:
    segments: list[Segment]

    @property
    def range(self) -> str:
        return f"{format_timestamp(self.segments[0].start)}–{format_timestamp(self.segments[-1].end)}"

    @property
    def text(self) -> str:
        return "\n".join(f"[{format_timestamp(s.start)}] {s.text}" for s in self.segments)


def pack_segments(segments: list[Segment], seconds: float | None = None) -> list[Segment]:
    """Join consecutive segments into lines of about `seconds` (default: config.LINE_SECONDS),
    ending at a sentence end when possible; a line never runs past twice that."""
    seconds = config.LINE_SECONDS if seconds is None else seconds
    lines: list[Segment] = []
    current: list[Segment] = []
    for segment in segments:
        current.append(segment)
        length = segment.end - current[0].start
        sentence_end = segment.text.rstrip().endswith((".", "?", "!", "…"))
        if (length >= seconds and sentence_end) or length >= 2 * seconds:
            lines.append(_join(current))
            current = []
    if current:
        lines.append(_join(current))
    return lines


def _join(segments: list[Segment]) -> Segment:
    text = " ".join(s.text.strip() for s in segments if s.text.strip())
    return Segment(segments[0].start, segments[-1].end, text)


def load_segments(folder: Path) -> list[Segment]:
    """The transcript as the LLM sees it: Whisper's segments packed into lines."""
    return pack_segments([Segment(**s) for s in json.loads((folder / SEGMENTS_NAME).read_text())])


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


def language_name(code: str) -> str:
    """'es' -> the name the prompts use ("Write in Spanish (as spoken in Costa Rica)")."""
    return LANGUAGE_NAMES.get(code, code or "the transcript's language")


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


def ask(prompt: str, model: type[Model], stats: LLMStats | None = None) -> Model:
    """One LLM call returning a validated `model`. On invalid output, retry once with the
    error in the conversation: at temperature 0 a plain retry would repeat the same answer.
    Each reply's counters are added to `stats` (retries included: they cost time too)."""
    check_budget(prompt)
    stats = LLMStats() if stats is None else stats
    schema = model.model_json_schema()
    messages = [{"role": "user", "content": prompt}]
    reply = _chat(messages, schema)
    stats.add(reply)
    try:
        return model.model_validate_json(reply.message.content)
    except ValidationError as first:
        messages += [
            {"role": "assistant", "content": reply.message.content},
            {"role": "user", "content": f"That JSON was invalid:\n{first}\nReturn corrected JSON only."},
        ]
    reply = _chat(messages, schema)
    stats.add(reply)
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
    folder: Path,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    stats: LLMStats | None = None,
) -> list[ChunkExtraction]:
    """Chunk the transcript and extract each chunk; saves extractions.json.
    LLM stats are added to `stats` (if given) and saved in meta.json."""
    stats = LLMStats() if stats is None else stats
    segments = load_segments(folder)
    language = language_name(json.loads((folder / "meta.json").read_text()).get("language", ""))

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
        results.append(ask(prompt, ChunkExtraction, stats))
        on_progress(n, len(chunks))

    _write_json(
        folder / EXTRACTIONS_NAME,
        [{"range": c.range, **r.model_dump()} for c, r in zip(chunks, results)],
    )
    save_stats(folder, "extract", stats)
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
    return [t for t in merged if timestamp_seconds(t.end) - timestamp_seconds(t.start)
            >= config.MIN_TANGENT_SECONDS]


def _seconds(item) -> float:
    return timestamp_seconds(item["end"]) - timestamp_seconds(item["start"])


def _fold_short_topics(topics: list[dict]) -> list[dict]:
    """Topics shorter than MIN_TOPIC_SECONDS join the previous one (the first joins the next)."""
    kept: list[dict] = []
    for topic in topics:
        if kept and _seconds(topic) < config.MIN_TOPIC_SECONDS:
            kept[-1]["end"] = topic["end"]
        else:
            kept.append(topic)
    if len(kept) > 1 and _seconds(kept[0]) < config.MIN_TOPIC_SECONDS:
        kept[1]["start"] = kept[0]["start"]
        kept.pop(0)
    return kept


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
    plain = _plain(text)
    if not plain or plain in NOT_SAID | vague or plain.startswith(NOT_SAID_PREFIXES):
        return None
    return text.strip()


def _first(values, vague: set[str] = frozenset()) -> str | None:
    """First real value, or None: unknowns stay None for the renderer to localize."""
    return next((v for v in (_value(v, vague) for v in values) if v), None)


def _sentence(text: str, period: bool = False) -> str:
    """Money normalized, stray CJK characters removed, first letter capitalized. Sentences
    (`period`) end with a period; labels and to-dos don't, so lists and tables read the same
    in every row."""
    text = normalize_money(CJK_RE.sub("", text).strip()).rstrip(". ")
    text = text[:1].upper() + text[1:]
    return text + "." if period and text and text[-1] not in "?!" else text


def _combine_topics(spans: list[TopicSpan]) -> dict:
    spans = sorted(spans, key=lambda t: timestamp_seconds(t.start))
    return {"title": _sentence(spans[0].title), "start": spans[0].start,
            "end": max((t.end for t in spans), key=timestamp_seconds)}


def _combine_entry(points: list[Point]) -> dict:
    points, timestamps = _timeline(points)
    return {"text": _sentence(points[0].text, period=True), "timestamps": timestamps}


def _role(item: Commitment) -> str:
    """The owner role of one mention; a pronoun in `who` overrides the model's choice."""
    who = _plain(item.who)
    return "recipients" if who in RECIPIENTS else "speaker" if who in SPEAKER else item.owner


def _combine_commitment(items: list[Commitment]) -> dict:
    """Most specific owner across mentions: a named person, else the speaker or the recipients
    (first mention that says), else nobody."""
    items, timestamps = _timeline(items)
    who = _first((i.who for i in items), RECIPIENTS | SPEAKER)
    roles = [r for r in map(_role, items) if r in ("speaker", "recipients")]
    owner = "person" if who else (roles[0] if roles else "nobody")
    return {"what": _sentence(items[0].what), "owner": owner, "who": who,
            "due": _first((i.due for i in items), VAGUE_DUE), "timestamps": timestamps}


def _describe(field: str, item) -> str:
    if field == "topics":
        return f"({item.start}–{item.end}) {item.title}"
    if field == "commitments":
        who = item.who or OWNER_NAMES.get(_role(item), "nobody named")
        return f"({item.timestamp}) {who} · {item.due or 'no deadline'} · {item.what}"
    return f"({item.timestamp}) {item.text}"


def _merge_plan(pools: dict[str, list], stats: LLMStats) -> MergePlan:
    """Ask the LLM which items are the same fact. Returns number groups (1-based)."""
    sections = []
    for field in GROUPED_FIELDS:
        lines = [f"[{n}] {_describe(field, item)}" for n, item in enumerate(pools[field], 1)]
        sections.append(f"## {field}\n" + ("\n".join(lines) or "(none)"))
    return ask(load_prompt("merge", items="\n\n".join(sections)), MergePlan, stats)


def _topic_of(timestamp: str, topics: list[Topic]) -> str | None:
    """The topic being discussed at `timestamp`: the latest topic that started by then."""
    at = timestamp_seconds(timestamp)
    started = [t for t in topics if timestamp_seconds(t.start) <= at]
    return started[-1].id if started else (topics[0].id if topics else None)


def _in_tangent(seconds: float, tangents: list[Tangent]) -> bool:
    """Timestamps are whole seconds (02:13 = 133.0–133.9 s), so a range ends a second later."""
    return any(timestamp_seconds(t.start) <= seconds < timestamp_seconds(t.end) + 1 for t in tangents)


def _covered(timestamp: str, tangents: list[Tangent], meeting_times: set[str]) -> bool:
    """An observation that only repeats a tangent (same range) or the next meeting."""
    return _in_tangent(timestamp_seconds(timestamp), tangents) or timestamp in meeting_times


def _details(meta: dict) -> dict:
    """Sender and date: --sender / --date if given, else the date in a WhatsApp file name."""
    return {"sender": meta.get("sender"),
            "memo_date": meta.get("date") or ingest.date_from_name(meta.get("source_name", ""))}


def _source(folder: Path, segments_end: float) -> Source:
    meta = json.loads((folder / "meta.json").read_text())
    seconds = meta.get("transcription", {}).get("audio_seconds", segments_end)
    return Source(**_details(meta), duration=format_timestamp(seconds),
                  language=meta.get("language", ""))


def refresh_source(folder: Path) -> None:
    """Copy sender/date from meta.json into minutes.json, if it exists: they only change the
    header, so a --sender / --date fix needs no new LLM calls."""
    if not is_merged(folder):
        return
    minutes = Minutes.model_validate_json((folder / MINUTES_NAME).read_text())
    meta = json.loads((folder / "meta.json").read_text())
    minutes.source = minutes.source.model_copy(update=_details(meta))
    _write_json(folder / MINUTES_NAME, minutes.model_dump())


def _specificity(m: NextMeeting) -> tuple:
    filled = sum(1 for v in [m.day, m.time, m.place] if _value(v))
    return filled, any(ch.isdigit() for ch in m.day), timestamp_seconds(m.timestamp)


def _context(timestamp: str, lines: list[Segment]) -> str:
    """The transcript line at `timestamp` with one line before and after (~50 s)."""
    at = timestamp_seconds(timestamp)
    i = max([n for n, line in enumerate(lines) if line.start <= at] or [0])
    return "\n".join(f"[{format_timestamp(l.start)}] {l.text}" for l in lines[max(0, i - 1):i + 2])


def _verify_owner(c: MinutesCommitment, lines: list[Segment], language: str,
                  stats: LLMStats) -> MinutesCommitment:
    """Ask again, in a small focused call, who has to do this. Owner was the weakest part of
    extraction: one big prompt mixed up the speaker, the recipients and reported speech."""
    prompt = load_prompt("verify_owner", what=c.what, language=language,
                         context=_context(c.timestamps[0], lines))
    check = ask(prompt, OwnerCheck, stats)
    who = _value(check.who, RECIPIENTS | SPEAKER) if check.owner == "person" else None
    plain = _plain(check.who)
    owner = ("recipients" if plain in RECIPIENTS else "speaker" if plain in SPEAKER
             else "person" if who else "nobody" if check.owner == "person" else check.owner)
    return c.model_copy(update={"owner": owner, "who": who})


def is_merged(folder: Path) -> bool:
    return (folder / MINUTES_NAME).exists()


def merge(folder: Path, stats: LLMStats | None = None) -> tuple[Minutes, int]:
    """Combine extractions.json into minutes.json. Returns (minutes, duplicates removed)."""
    stats = LLMStats() if stats is None else stats
    chunks = [ChunkExtraction.model_validate(c)
              for c in json.loads((folder / EXTRACTIONS_NAME).read_text())]
    pools = {field: [item for c in chunks for item in getattr(c, field)] for field in GROUPED_FIELDS}

    # One chunk: extraction already listed each fact once, so there is nothing to group.
    needs_llm = len(chunks) > 1 and any(len(items) > 1 for items in pools.values())
    plan = _merge_plan(pools, stats) if needs_llm else MergePlan(**{
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
    topic_data = _fold_short_topics(topic_data)
    topics = [Topic(id=f"T{n}", **t) for n, t in enumerate(topic_data, 1)]

    tangents = _merge_tangents([t for c in chunks for t in c.tangents])
    meetings = sorted((m for c in chunks for m in c.next_meeting),
                      key=lambda m: timestamp_seconds(m.timestamp))
    meeting_times = {m.timestamp for m in meetings}

    entries = {}
    for field, prefix in ENTRY_FIELDS.items():
        data = sorted((e for e in map(_combine_entry, grouped[field]) if _value(e["text"])),
                      key=lambda e: timestamp_seconds(e["timestamps"][0]))
        if field == "observations":  # each fact in one field, even when the model repeats it
            data = [e for e in data if not _covered(e["timestamps"][0], tangents, meeting_times)]
        entries[field] = [Entry(id=f"{prefix}{n}", topic=_topic_of(e["timestamps"][0], topics), **e)
                          for n, e in enumerate(data, 1)]
    commitment_data = sorted((c for c in map(_combine_commitment, grouped["commitments"])
                              if _value(c["what"])),
                             key=lambda c: timestamp_seconds(c["timestamps"][0]))
    commitments = [MinutesCommitment(id=f"C{n}", topic=_topic_of(c["timestamps"][0], topics), **c)
                   for n, c in enumerate(commitment_data, 1)]
    if topics:  # the last topic runs at least until the last item filed under it
        last_items = [ts for e in [*commitments, *(x for v in entries.values() for x in v)]
                      if e.topic == topics[-1].id for ts in e.timestamps]
        topics[-1].end = max([topics[-1].end, *last_items], key=timestamp_seconds)

    infos = [m for c in chunks for m in c.meeting]
    # The most specific mention ("el 5 de diciembre" over "en diciembre"); among equals the
    # last one, which is usually the final word.
    last = max(meetings, key=_specificity) if meetings else None
    segments = json.loads((folder / SEGMENTS_NAME).read_text())
    source = _source(folder, segments[-1]["end"] if segments else 0)
    lines = load_segments(folder)
    if lines:
        commitments = [_verify_owner(c, lines, language_name(source.language), stats)
                       for c in commitments]
    minutes = Minutes(
        source=source,
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
    save_stats(folder, "merge", stats)
    kept = len(topics) + len(commitments) + sum(len(e) for e in entries.values())
    return minutes, sum(len(pool) for pool in pools.values()) - kept


# --- 3c write the prose -------------------------------------------------------------

def _owner(c: MinutesCommitment) -> str:
    return c.who or OWNER_NAMES.get(c.owner, "nobody named")


def _topic_items(minutes: Minutes, topic_id: str | None = None) -> str:
    """The extracted items (of one topic, or all), one per line, for the prompts."""
    lines = [f"- Agreement: {a.text}" for a in minutes.agreements if topic_id in (None, a.topic)]
    lines += [f"- Commitment: {_owner(c)} · {c.due or 'no deadline'} · {c.what}"
              for c in minutes.commitments if topic_id in (None, c.topic)]
    lines += [f"- Pending: {p.text}" for p in minutes.pending if topic_id in (None, p.topic)]
    lines += [f"- Observation: {o.text}" for o in minutes.observations if topic_id in (None, o.topic)]
    return "\n".join(lines) or "(none)"


def _topic_transcript(topic: Topic, last: bool, segments: list[Segment],
                      tangents: list[Tangent]) -> str:
    """The transcript lines of one topic, without its digressions. A topic runs until the next
    one starts; the last one runs to the end of the memo (closing remarks belong to it)."""
    start = timestamp_seconds(topic.start)
    end = float("inf") if last else timestamp_seconds(topic.end)
    return "\n".join(f"[{format_timestamp(s.start)}] {s.text.strip()}" for s in segments
                     if start <= s.start < end and not _in_tangent(s.start, tangents))


def is_written(folder: Path) -> bool:
    return (folder / PROSE_NAME).exists()


def write(
    folder: Path,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    stats: LLMStats | None = None,
) -> Prose:
    """Write the minuta's prose into prose.json: one call per topic, then one for the overview."""
    stats = LLMStats() if stats is None else stats
    minutes = Minutes.model_validate_json((folder / MINUTES_NAME).read_text())
    segments = load_segments(folder)
    language = language_name(minutes.source.language)
    total = len(minutes.topics) + 1

    developments: dict[str, str | None] = {}
    for n, topic in enumerate(minutes.topics, 1):
        transcript = _topic_transcript(topic, n == len(minutes.topics), segments, minutes.tangents)
        if transcript:  # no lines (bad timestamps, all digression): nothing to write from
            prompt = load_prompt("develop", title=topic.title, range=f"{topic.start}–{topic.end}",
                                 language=language, items=_topic_items(minutes, topic.id),
                                 transcript=transcript)
            text = _value(ask(prompt, Development, stats).development)
            developments[topic.id] = _sentence(text, period=True) if text else None
        else:
            developments[topic.id] = None
        on_progress(n, total)

    # Nothing extracted: asking for a summary of nothing only invites invention.
    has_content = minutes.topics or minutes.agreements or minutes.commitments or minutes.pending
    overview = None
    if has_content:
        topics = "\n\n".join(f"### {t.title}\n{developments[t.id] or '(no details)'}"
                              for t in minutes.topics) or "(none)"
        overview = ask(load_prompt("overview", language=language, topics=topics,
                                   items=_topic_items(minutes)), Overview, stats)
    on_progress(total, total)

    title = _value(_sentence(overview.title)) if overview else None
    summary = _value(overview.summary) if overview else None
    prose = Prose(title=title, summary=_sentence(summary, period=True) if summary else None,
                  developments=developments)
    _write_json(folder / PROSE_NAME, prose.model_dump())
    save_stats(folder, "write", stats)
    return prose
