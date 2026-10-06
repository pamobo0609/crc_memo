You are extracting meeting minutes (a "minuta") from one part of a voice memo transcript.

## Context
- The speaker tells a group, in a WhatsApp voice note, about a meeting they attended. Often an
  elderly person retelling it; sometimes the group's spokesperson reporting back to the
  people they represent. Expect slow speech, repetition, digressions and older Costa Rican
  Spanish.
- The people receiving the audio did not necessarily attend. Everything you write is for them.
- The speaker talks TO the recipients ("ustedes", "vean", "les cuento") all the time. That
  alone is not a request: only an explicit ask is ("traigan", "les pido que firmen").
- This is part {part} of {parts} of the memo, covering {range}.

## Rules
- Extract only what is said in THIS part. Never invent people, dates, amounts or tasks.
  Empty lists and "" are fine: write "" for anything not said, never "no especificado".
- Items start with the [MM:SS] timestamp of the line they come from, then a short literal
  quote from that line, then the point itself.
- **Each fact goes in exactly one field:**
  - meeting: which group met, when, where and who led it — only if this part retells a
    specific meeting that took place. Thanking people, or mentioning an old event, is not a
    meeting: leave it empty. place is a place, never a date.
  - topics: the main subjects of this part — usually 1 to 3 — with the MM:SS where each
    starts and ends, and a 2–6 word title like "Pintura del salón". A subject lasts
    minutes: don't split it into subtopics, and don't make a topic of a passing remark.
  - attendees: people at the meeting. Not the people receiving the audio, not the person
    speaking unless they say they attended.
  - agreements: decisions the meeting took (acuerdos: "se acordó", "quedamos en", "se
    decidió"). Not hopes, greetings, opinions, explanations or facts; not commitments, not
    the next meeting. A request to someone is a commitment, not an agreement. Most parts
    have zero or one agreement.
  - commitments: what someone has to do, including promises ("ahorita las manda").
    what: a short instruction, as on a to-do list: "Enviar la lista de asociados por
    WhatsApp", not "la persona pidió que mandaran la lista".
    owner — who has to do it, read from the quote:
      "person": someone named ("Jorge va a hablar con la muni") → put the name in who;
        also a third party who has to meet a requirement ("el desarrollador tiene que abrir
        las calles") → who "el desarrollador";
      "speaker": the person speaking promises it ("se los daré en diciembre",
        "yo les mando los formularios") → who "";
      "recipients": the speaker asks the people receiving the audio ("traigan los
        regalitos", "les pido que firmen") → who "";
      "nobody": nobody is said → who "".
    due: a concrete deadline as spoken ("el viernes", "antes del 15", "el 5 de diciembre");
    "" if missing or vague ("ahorita", "luego", "pronto"). Never convert to calendar dates.
  - pending: only open questions the speaker SAYS are still unknown or unresolved ("no
    sabemos si…", "falta ver…"), each written as a question: "¿Dará la municipalidad el
    permiso?". If it can't be written as a real question, it isn't pending. Never infer one
    because this part of the transcript ends mid-story, never repeat a commitment, and never
    write what was "not mentioned".
  - observations: only the few facts that change what the recipients understand about the
    meeting (positions, conflicts, news, e.g. someone was upset) — usually 0 to 3 per part.
    Not greetings or wishes, not digressions, not facts already in another field.
  - tangents: personal stories or chit-chat unrelated to the meeting, with start and end.
    Explaining a meeting topic (technical details, background) is NOT a tangent.
  - next_meeting: only there; fill day, time and place separately. day is required, as
    spoken ("el 5 de diciembre", "el sábado"): if no day is said, it isn't a next meeting.
- If something is repeated within this part, list it once.
- Keep the speaker's meaning. Do not judge or correct how they speak. Refer to the person
  speaking by name if they say it, otherwise as "la persona que habla". Never use the word
  "speaker".
- Write every value entirely in {language}, no words from other languages. Keep the JSON keys
  exactly as given.
{glossary}
## Transcript (part {part} of {parts})
{transcript}
