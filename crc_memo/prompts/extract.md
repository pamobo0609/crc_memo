You are extracting meeting minutes from one part of a voice memo transcript.

## Context
- The speaker is retelling a meeting they attended, in a WhatsApp voice note. Speakers are
  often elderly: expect slow speech, repetition, digressions and older Costa Rican Spanish.
- The listener ("usted") did not attend the meeting. Everything you write is for the listener.
- This is part {part} of {parts} of the memo, covering {range}.

## Rules
- Extract only what is said in THIS part. Never invent people, dates, amounts or tasks.
  Empty lists are fine.
- Every item starts with the [MM:SS] timestamp of the line it comes from, then a short literal
  quote from that line, then the point itself.
- **Each fact goes in exactly one field:**
  - decisions: what the meeting agreed (acuerdos). Not tasks, not the next meeting. A decision
    is not also a task unless a specific person is named to do it.
  - action_items: what a specific person must do, including promises ("ahorita las manda"
    is a task with due "sin fecha").
  - open_questions: only what the speaker SAYS is still unknown or unresolved. Never infer
    one because this part of the transcript ends mid-story.
  - notable: other important facts (e.g. someone was upset). Not digressions.
  - tangents: personal stories or chit-chat unrelated to the meeting, with their range.
  - next_meeting: only there; fill day, time and place separately.
- topics: short labels of 2–6 words, like "Pintura del salón".
- participants: people at the meeting. Not the listener ("usted"), not the person speaking.
- owner: the person named ("Doña Rosa", "el tesorero"). If the speaker asks the listener to do
  something, owner is "usted". If nobody is named, "sin asignar". Never guess.
- due: as spoken ("el viernes", "antes del 15"). Vague or missing ("ahorita", "luego") is
  "sin fecha". Never convert to calendar dates.
- Money: in text, task and summary fields write amounts in colones with ₡, converting
  Costa Rican slang: "cinco rojos" → "₡5.000", "un tucán" → "₡5.000", "una teja" → "₡100",
  "medio palo" → "₡500.000", "un palo" → "₡1.000.000". Quotes stay literal.
- If something is repeated within this part, list it once.
- Keep the speaker's meaning. Do not judge or correct how they speak. Refer to the person speaking
  by name if they say it, otherwise as "la persona que habla". Never use the word "speaker".
- Write every value entirely in {language}, no words from other languages. Keep the JSON keys
  exactly as given.
{glossary}
## Transcript (part {part} of {parts})
{transcript}
