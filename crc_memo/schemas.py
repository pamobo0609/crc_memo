"""Shapes of what the LLM returns.

One Pydantic class gives us both:
- the JSON schema sent to Ollama (`format=`), which constrains the output to valid JSON, and
- the validation of the reply (`model_validate_json`), which turns it into Python objects.

Field order is deliberate: `timestamp` and `quote` come first, so the model writes the evidence
*before* the claim (generation runs left to right) instead of inventing a quote afterwards.
"""

from typing import Annotated

from pydantic import BaseModel, Field

# Length limits become `maxLength` in the JSON schema, which Ollama's constrained decoding
# enforces. Output length is what makes local extraction slow (~12 tokens/s), and long
# fields invite rambling and duplication.
Label = Annotated[str, Field(max_length=60)]
Quote = Annotated[str, Field(max_length=120)]
Sentence = Annotated[str, Field(max_length=200)]

TIMESTAMP = "MM:SS of the transcript line where this is said, copied from its [MM:SS] marker"
QUOTE = "short literal quote from the transcript (max ~15 words) that supports this"


class Point(BaseModel):
    timestamp: str = Field(description=TIMESTAMP)
    quote: Quote = Field(description=QUOTE)
    text: Sentence = Field(description="the point, stated clearly in one sentence")


class ActionItem(BaseModel):
    timestamp: str = Field(description=TIMESTAMP)
    quote: Quote = Field(description=QUOTE)
    task: Sentence = Field(description="what has to be done, as a short imperative")
    owner: Label = Field(
        description='the person named; "usted" if the speaker asks the listener; else "sin asignar"'
    )
    due: Label = Field(description='as spoken, e.g. "el viernes"; "sin fecha" if none or vague')


class Tangent(BaseModel):
    range: str = Field(description="MM:SS–MM:SS of the digression")
    summary: Sentence = Field(description="one line: what the digression is about")


class NextMeeting(BaseModel):
    timestamp: str = Field(description=TIMESTAMP)
    quote: Quote = Field(description=QUOTE)
    # Separate fields: a single "when" got "el sábado 25" and silently dropped the time.
    day: Label = Field(description='day or date as spoken, e.g. "el sábado 25"')
    time: Label = Field(description='time as spoken, e.g. "a las 3 de la tarde"; "" if not said')
    place: Label = Field(description='place as spoken; "" if not said')


class ChunkExtraction(BaseModel):
    topics: list[Label] = Field(description="meeting topics in this part: 2-6 word labels, no timestamps")
    participants: list[Label] = Field(description="people mentioned as attending or speaking, with role if said")
    decisions: list[Point] = Field(description="agreements the meeting reached (acuerdos)")
    action_items: list[ActionItem] = Field(description="tasks someone has to do (tareas)")
    open_questions: list[Point] = Field(description="things left unresolved (pendientes)")
    notable: list[Point] = Field(description="other important facts worth knowing")
    tangents: list[Tangent] = Field(description="digressions unrelated to the meeting, safe to skip")
    next_meeting: list[NextMeeting] = Field(description="the next meeting, if mentioned: 0 or 1 items")


# --- Merge (3b) ---------------------------------------------------------------
# The LLM only groups item numbers; code builds the merged items, so merging can't change
# a name, amount or quote.

GROUPS = "one group per distinct fact; every item number appears in exactly one group"


class Group(BaseModel):
    # The fact comes first (evidence first, again): naming *what* the group is before
    # choosing its numbers stopped bare-number answers from mixing up facts.
    fact: Sentence = Field(description="the single fact these items state, in one short sentence")
    items: list[int] = Field(description="numbers of the items that state exactly this fact")


class MergePlan(BaseModel):
    decisions: list[Group] = Field(description=GROUPS)
    action_items: list[Group] = Field(description=GROUPS)
    open_questions: list[Group] = Field(description=GROUPS)
    notable: list[Group] = Field(description=GROUPS)


class MergedPoint(BaseModel):
    timestamps: list[str]  # every time the point was mentioned, in order
    quote: str
    text: str


class MergedAction(BaseModel):
    timestamps: list[str]
    quote: str
    task: str
    owner: str
    due: str


class Merged(BaseModel):
    topics: list[str]
    participants: list[str]
    decisions: list[MergedPoint]
    action_items: list[MergedAction]
    open_questions: list[MergedPoint]
    notable: list[MergedPoint]
    tangents: list[Tangent]
    next_meeting: list[NextMeeting]
