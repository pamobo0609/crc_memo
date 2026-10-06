You are extracting meeting minutes (a "minuta") from one part of a voice memo transcript.

## Context
- The speaker is retelling a meeting they attended, in a WhatsApp voice note sent to a group.
  Speakers are often elderly: expect slow speech, repetition, digressions and older Costa
  Rican Spanish.
- The people receiving the audio did not necessarily attend. Everything you write is for them.
- This is part {part} of {parts} of the memo, covering {range}.

## Rules
- Extract only what is said in THIS part. Never invent people, dates, amounts or tasks.
  Empty lists and "" are fine.
- Items start with the [MM:SS] timestamp of the line they come from, then a short literal
  quote from that line, then the point itself.
- **Each fact goes in exactly one field:**
  - meeting: which group met, when, where and who led it — only if this part says so.
  - topics: the meeting topics in this part, with the MM:SS where each starts and ends,
    and a 2–6 word title like "Pintura del salón".
  - attendees: people at the meeting. Not the people receiving the audio, not the person
    speaking unless they say they attended.
  - agreements: what the meeting agreed (acuerdos). Not commitments, not the next meeting.
  - commitments: what someone has to do, including promises ("ahorita las manda").
    what: a short instruction, as on a to-do list: "Enviar la lista de asociados por
    WhatsApp", not "la persona pidió que mandaran la lista".
    who: the person named, or "" if nobody is named.
    for_recipients: true only if the speaker asks the people receiving the audio
    ("usted", "ustedes", "les pido a todos").
    due: as spoken ("el viernes", "antes del 15"); "" if missing or vague ("ahorita", "luego").
    Never convert to calendar dates.
  - pending: only what the speaker SAYS is still unknown or unresolved. Never infer one
    because this part of the transcript ends mid-story.
  - observations: other important facts (e.g. someone was upset). Not digressions.
  - tangents: personal stories or chit-chat unrelated to the meeting, with start and end.
  - next_meeting: only there; fill day, time and place separately.
- If something is repeated within this part, list it once.
- Keep the speaker's meaning. Do not judge or correct how they speak. Refer to the person
  speaking by name if they say it, otherwise as "la persona que habla". Never use the word
  "speaker".
- Write every value entirely in {language}, no words from other languages. Keep the JSON keys
  exactly as given.
{glossary}
## Transcript (part {part} of {parts})
{transcript}
