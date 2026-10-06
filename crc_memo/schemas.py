"""Shapes of what the LLM returns, and of the minutes we build from it.

The output is a *minuta* (meeting minutes), and every field below exists because the minuta
renders it. One Pydantic class gives us both:
- the JSON schema sent to Ollama (`format=`), which constrains the output to valid JSON, and
- the validation of the reply (`model_validate_json`), which turns it into Python objects.

Field order is deliberate: `timestamp` and `quote` come first, so the model writes the evidence
*before* the claim (generation runs left to right) instead of inventing a quote afterwards.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# Length limits become `maxLength` in the JSON schema, which Ollama's constrained decoding
# enforces. Output length is what makes local extraction slow (~12 tokens/s), and long
# fields invite rambling and duplication.
Label = Annotated[str, Field(max_length=60)]
Quote = Annotated[str, Field(max_length=120)]
Sentence = Annotated[str, Field(max_length=200)]

TIMESTAMP = "MM:SS of the transcript line where this is said, copied from its [MM:SS] marker"
# Who has to do a commitment. An explicit choice: with a bool "for the recipients", the model
# marked anything said to "ustedes" as the recipients' task, even "se los daré en diciembre"
# (the speaker's own promise). A spokesperson reporting back says "ustedes" in every sentence.
Owner = Literal["person", "speaker", "recipients", "nobody"]
OWNER = (
    'who does it: "person" = someone named (put the name in who); "speaker" = the person '
    'speaking promises to do it ("yo les mando", "se los daré"); "recipients" = the speaker asks '
    'the people receiving the audio to do it ("traigan", "les pido que firmen"); "nobody" = not said'
)
QUOTE = "short literal quote from the transcript (max ~15 words) that supports this"


# --- 3a: what the LLM extracts from one chunk -------------------------------------

class MeetingInfo(BaseModel):
    group: Label = Field(description='the group or organization that met, as named; "" if not said')
    when: Label = Field(description='when the meeting happened, as spoken (e.g. "ayer"); "" if not said')
    place: Label = Field(description='where it happened, as spoken; "" if not said')
    chaired_by: Label = Field(description='who led the meeting; "" if not said')


class TopicSpan(BaseModel):
    start: str = Field(description="MM:SS where the speaker starts talking about this topic")
    end: str = Field(description="MM:SS where the speaker moves on")
    title: Label = Field(description='2-6 word title, e.g. "Pintura del salón"')


class Point(BaseModel):
    timestamp: str = Field(description=TIMESTAMP)
    quote: Quote = Field(description=QUOTE)
    text: Sentence = Field(description="the point, stated clearly in one sentence")


class Commitment(BaseModel):
    timestamp: str = Field(description=TIMESTAMP)
    quote: Quote = Field(description=QUOTE)
    what: Sentence = Field(description="what has to be done, as a short imperative")
    owner: Owner = Field(description=OWNER)
    who: Label = Field(description='the name of the person, only when owner is "person"; else ""')
    due: Label = Field(description='concrete deadline as spoken, e.g. "el viernes"; "" if none or vague')


class Tangent(BaseModel):
    start: str = Field(description="MM:SS where the digression starts")
    end: str = Field(description="MM:SS where it ends")
    summary: Sentence = Field(description="one line: what the digression is about")


class NextMeeting(BaseModel):
    timestamp: str = Field(description=TIMESTAMP)
    quote: Quote = Field(description=QUOTE)
    # Separate fields: a single "when" got "el sábado 25" and silently dropped the time.
    day: Label = Field(description='day or date as spoken, e.g. "el sábado 25"')
    time: Label = Field(description='time as spoken, e.g. "a las 3 de la tarde"; "" if not said')
    place: Label = Field(description='place as spoken; "" if not said')


class ChunkExtraction(BaseModel):
    meeting: list[MeetingInfo] = Field(description="the meeting being retold, if this part says: 0 or 1 items")
    topics: list[TopicSpan] = Field(description="meeting topics in this part, in order")
    attendees: list[Label] = Field(description="people at the meeting, with role if said")
    agreements: list[Point] = Field(description="what the meeting agreed (acuerdos)")
    commitments: list[Commitment] = Field(description="what someone has to do (compromisos)")
    pending: list[Point] = Field(description="what the speaker says is still unresolved (pendientes)")
    observations: list[Point] = Field(description="other important facts, e.g. someone was upset")
    tangents: list[Tangent] = Field(description="digressions unrelated to the meeting, safe to skip")
    next_meeting: list[NextMeeting] = Field(description="the next meeting, if mentioned: 0 or 1 items")


# --- 3b: the merge plan (the LLM only groups item numbers) ---------------------------

GROUPS = "one group per distinct fact; every item number appears in exactly one group"


class Group(BaseModel):
    # The fact comes first (evidence first, again): naming *what* the group is before
    # choosing its numbers stopped bare-number answers from mixing up facts.
    fact: Sentence = Field(description="the single fact (or topic) these items state, in one short sentence")
    items: list[int] = Field(description="numbers of the items that state exactly this fact")


class OwnerCheck(BaseModel):  # 3b: one focused call per commitment, after merging
    # Reported speech first: deciding it before the owner is what keeps "yo les dije,
    # pásenme las notas" (said to a third party) from becoming a request to the recipients.
    reported_speech: bool = Field(
        description="true if the request is the speaker repeating what was said to someone else"
    )
    owner: Owner = Field(description=OWNER)
    who: Label = Field(description='the name or party, only when owner is "person"; else ""')


class MergePlan(BaseModel):
    topics: list[Group] = Field(description=GROUPS)
    agreements: list[Group] = Field(description=GROUPS)
    commitments: list[Group] = Field(description=GROUPS)
    pending: list[Group] = Field(description=GROUPS)
    observations: list[Group] = Field(description=GROUPS)


# --- 3b output = the contract the minuta is rendered from (minutes.json) -----------------
# Unknown values are None (not Spanish words), so the renderer localizes them.

class Source(BaseModel):
    sender: str | None
    memo_date: str | None
    duration: str
    language: str


class Meeting(BaseModel):
    group: str | None
    when: str | None
    place: str | None
    chaired_by: str | None


class Topic(BaseModel):
    id: str  # T1, T2… in time order
    title: str
    start: str
    end: str


class Evidence(BaseModel):
    """Where and how a point was said: the claim can always be checked against the audio."""
    timestamp: str
    quote: str  # literal words, as the model copied them from the transcript
    verified: bool = False  # the quote was found in the transcript near that time (in code)


class WithEvidence(BaseModel):
    evidence: list[Evidence]  # one per distinct time it was mentioned, in time order

    @model_validator(mode="before")
    @classmethod
    def _from_timestamps(cls, data):
        """minutes.json from before Phase 4 has only `timestamps`: keep them, without quotes
        (`memo reprocess ID --from merge` brings the quotes back from extractions.json)."""
        if isinstance(data, dict) and "evidence" not in data and "timestamps" in data:
            data = dict(data)
            data["evidence"] = [{"timestamp": ts, "quote": ""} for ts in data.pop("timestamps")]
        return data

    @property
    def timestamps(self) -> list[str]:
        return [e.timestamp for e in self.evidence]


class Entry(WithEvidence):  # an agreement, a pending point or an observation
    id: str  # A1 / P1 / O1
    topic: str | None  # topic id
    text: str


class MinutesCommitment(WithEvidence):
    id: str  # C1
    topic: str | None
    what: str
    owner: Owner
    who: str | None  # only for owner == "person"
    due: str | None


class MinutesNextMeeting(BaseModel):
    day: str | None
    time: str | None
    place: str | None


class Provenance(BaseModel):
    """What produced these minutes, so any line can be traced to its audio, models and code."""
    memo_id: str | None
    audio_sha256: str | None
    audio_name: str | None
    whisper: str | None  # model that transcribed it
    llm: str
    prompts: str  # short hash of crc_memo/prompts/*.md
    code: str | None  # crc_memo git commit ("+dirty" with uncommitted changes); None outside git


class Minutes(BaseModel):
    provenance: Provenance | None = None  # None in minutes.json written before Phase 4
    source: Source
    meeting: Meeting
    attendees: list[str]
    topics: list[Topic]
    agreements: list[Entry]
    commitments: list[MinutesCommitment]
    pending: list[Entry]
    observations: list[Entry]
    next_meeting: MinutesNextMeeting | None
    tangents: list[Tangent]


# --- 3c: the prose the LLM writes (code renders everything else) ----------------------

Paragraph = Annotated[str, Field(max_length=900)]


class Development(BaseModel):  # one call per topic, from that topic's transcript
    development: Paragraph = Field(
        description="2-5 sentences: what was discussed about this topic and how it ended"
    )


class Overview(BaseModel):  # one call, from the developments + items (not the transcript)
    # Groups also send complaints and announcements; forced into a minuta, those got an
    # invented meeting (a date as the place, two people thanked as "presidió").
    meeting_recap: bool = Field(
        description="true if the speaker retells a meeting that took place; false for other "
                    "messages (complaints, announcements, opinions)"
    )
    # Not a Label: maxLength cut a 60-character title mid-phrase ("…y la Asociación de").
    # No example name here: the model copied "Reunión de la Asociación de Vecinos" verbatim.
    title: Sentence = Field(description="3-8 words: which group met and its main subject")
    summary: Paragraph = Field(
        description="2-3 sentences: the most important outcomes, for someone who wasn't there"
    )


class Prose(BaseModel):  # prose.json, rendered together with minutes.json
    meeting_recap: bool | None = None  # None: unknown (nothing extracted, or an older prose.json)
    title: str | None
    summary: str | None
    developments: dict[str, str | None]  # topic id -> development
