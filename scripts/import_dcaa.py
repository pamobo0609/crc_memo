"""Convert the scanned DCAA (Diccionario de costarriqueñismos) PDF into JSON.

Run once:  uv run python scripts/import_dcaa.py dcaa.pdf

The PDF is a 2008 OCR scan: no bold, two columns, noisy characters. We rely on
layout instead of fonts: each entry starts at the column's left margin and its
continuation lines have a hanging indent (~11pt).

Steps:
  1. layout  — split each page at the gutter, read lines per column.
  2. entries — group lines into entries by hanging indent, rejoin hyphenated words.
  3. parse   — split each entry into headword, tags, senses and phrases ("//").
  4. write   — crc_memo/glossary/dcaa.json (tracked in git; rerunning is rarely needed).
"""

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import pdfplumber

FIRST_PAGE, LAST_PAGE = 31, 353  # dictionary body (A..Z)
INDENT_THRESHOLD = 6  # pt; entry starts sit at the margin, continuations ~11pt in
PROJECT_DIR = Path(__file__).parent.parent
OUT_PATH = PROJECT_DIR / "crc_memo" / "glossary" / "dcaa.json"
# Step 1 is slow; parse reruns reuse it. Gitignored.
LAYOUT_CACHE = PROJECT_DIR / "scripts" / ".cache" / "dcaa_layout.json"

# Grammar / usage abbreviations, plus the ways OCR mangles them.
OCR_ABBREV_FIXES = {
    "vulgo": "vulg.", "loco": "loc.", "afirmo": "afirm.", "sao": "sa.",
    "faino": "fam.", "pI.": "pl.", "prnl./I": "prnl. //",
}
TAGS = {
    "m.": "masculine noun", "f.": "feminine noun", "adj.": "adjective",
    "adv.": "adverb", "tr.": "transitive verb", "intr.": "intransitive verb",
    "prnl.": "pronominal verb", "interj.": "interjection", "pl.": "plural",
    "fr.": "phrase", "loc.": "locution", "expr.": "expression",
    "m. adv.": "adverbial phrase", "n.pr.": "proper noun",
    "fig.": "figurative", "fam.": "colloquial", "vulg.": "vulgar",
    "despect.": "derogatory", "irón.": "ironic", "Usáb.": "dated",
    "Bot.": "botany", "Zool.": "zoology", "Dep.": "sports", "afirm.": "affirmation",
    "interjec.": "interjection", "n. pr.": "proper noun", "n.pr.f.": "proper noun",
    "n.pr.m.": "proper noun",
    "proverb.": "proverb", "grosera.": "coarse", "Út.c.s.": "also as noun",
    "Út.c.prnl.": "also pronominal", "Út.c.intr.": "also intransitive",
}
TAG_ALT = "|".join(re.escape(t) for t in sorted(TAGS, key=len, reverse=True))
TAG_RE = re.compile(r"^\s*(" + TAG_ALT + r"|y)(?=\s|$)")
# "//" separates senses and phrases. OCR renders it many ways: "/ /", "1/", "/1",
# "/I", "II", "11", "J/"... ("112." is "// 2.").
SEP_RE = re.compile(
    r"\s*(?://|/ /|J/|(?<=\s)(?:1/|/1|/I|I/|II|lI|Il|ll|11)(?=\s|\d\s*\.))\s*"
)


# ---------- 1. layout ----------

def find_gutter(page):
    """Middle of the widest empty vertical strip between the two columns."""
    width = int(page.width) + 1
    occupied = [False] * width
    for ch in page.chars:
        # Skip the big letter heading ("O") that sits over the gutter on section pages.
        if ch["text"].strip() and ch["size"] < 20:
            for x in range(int(ch["x0"]), min(int(ch["x1"]) + 1, width)):
                occupied[x] = True
    best, best_span, start = page.width / 2, 0, None
    for x in range(int(page.width * 0.35), int(page.width * 0.65)):
        if not occupied[x]:
            start = x if start is None else start
            if x - start > best_span:
                best_span, best = x - start, (start + x) / 2
        else:
            start = None
    return best


def is_noise_line(text):
    """Page numbers, section letters, stray marks."""
    t = text.strip()
    return t.isdigit() or len(t) <= 2


def column_margin(lines):
    """Leftmost x shared by at least two lines (ignores stray marks)."""
    xs = sorted(l["x0"] for l in lines)
    for i in range(len(xs) - 1):
        if xs[i + 1] - xs[i] < 3:
            return xs[i]
    return xs[0] if xs else 0


def read_columns(pdf_path):
    """Yield (page_number, is_entry_start, text) for every line, in reading order."""
    with pdfplumber.open(pdf_path) as pdf:
        for n in range(FIRST_PAGE, LAST_PAGE + 1):
            page = pdf.pages[n - 1]
            gutter = find_gutter(page)
            for x0, x1 in ((0, gutter), (gutter, page.width)):
                col = page.crop((x0, 0, x1, page.height))
                lines = [l for l in col.extract_text_lines() if not is_noise_line(l["text"])]
                if not lines:
                    continue
                margin = column_margin(lines)
                for l in lines:
                    yield n, l["x0"] - margin < INDENT_THRESHOLD, l["text"].strip()
            print(f"\r  read page {n}/{LAST_PAGE}", end="", file=sys.stderr)
    print(file=sys.stderr)


# ---------- 2. entries ----------

def group_entries(lines):
    entries = []
    for page, starts, text in lines:
        if starts or not entries:
            entries.append({"page": page, "lines": [text]})
        else:
            entries[-1]["lines"].append(text)
    return entries


def merge_broken_entries(entries):
    """Repair indent misreads: an entry always ends with a period (or ! ? ).
    If the previous one stops mid-sentence, this "entry" is its continuation."""
    merged = []
    for e in entries:
        prev = merged[-1] if merged else None
        first = e["lines"][0]
        if prev and (
            not prev["lines"][-1].rstrip().endswith((".", "!", "?", ")"))
            or first[:1] in ",.;:"
        ):
            prev["lines"].extend(e["lines"])
        else:
            merged.append(e)
    return merged


WORD_RE = re.compile(r"[a-záéíóúüñ]+", re.I)


def build_vocab(entries):
    """Word counts across the whole book, used to rejoin split words."""
    vocab = Counter()
    for e in entries:
        for line in e["lines"]:
            vocab.update(w.lower() for w in WORD_RE.findall(line))
    return vocab


def join_lines(lines, vocab):
    """Join lines; 'fre' + 'cuente' becomes 'frecuente' when that's a known word."""
    text = lines[0]
    for nxt in lines[1:]:
        tail = re.search(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)-?$", text)
        head = re.match(r"([a-záéíóúüñ]+)", nxt)
        if tail and head:
            a, b = tail.group(1), head.group(1)
            joined = (a + b).lower()
            split_is_odd = vocab[a.lower()] < 3 or vocab[b.lower()] < 3
            if text.endswith("-") or (vocab[joined] >= 1 and split_is_odd):
                text = text[: tail.start()] + a + nxt
                continue
        text = text + " " + nxt
    return text


# ---------- 3. parse ----------

def fix_ocr(text):
    for bad, good in OCR_ABBREV_FIXES.items():
        text = re.sub(rf"(?<!\w){re.escape(bad)}(?!\w)", good, text)
    return text


def take_tags(text):
    """Strip leading grammar/usage abbreviations; return (tags, rest)."""
    tags = []
    while True:
        m = TAG_RE.match(text)
        if not m:
            return tags, text.strip()
        if m.group(1) != "y":
            tags.append(m.group(1))
        text = text[m.end():]


def fold(s):
    """Lowercase, strip accents: 'Cómo' -> 'como'. Used for matching."""
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# The headword ends at a period, a "(" or "[", or right before a grammar tag.
# Interjections keep their marks: "¡ah!". Homograph superscripts come through OCR as
# a trailing digit or "!" ("ajo2", "balde!") and are dropped.
HEAD_RE = re.compile(
    r"^(?P<head>[¡¿][^!?]{1,40}[!?](?:\s+o\s+[¡¿]?[^!?]{1,40}[!?])?|[^.\[(¡]+?)"
    r"(?P<sup>[0-9!]{1,2})?\s*•?'?"
    r"(?=\s*[.\[(]|\s+(?:" + TAG_ALT + r")(?:\s|$))"
    r"\s*\.?\s*"
    r"(?:\[[^\]]*\]\s*\.?\s*)?"            # optional pronunciation [a.bi.ga.él]
    r"(?:\((?P<etym>[^)]*)\)\.?\s*)?"      # optional etymology (Del ingl. comic.)
)


def parse_entry(raw):
    text = fix_ocr(raw["text"])
    text = re.sub(r"^(\S*?[a-zñ])0", r"\1o", text)  # OCR zero for "o": "aut02" -> "auto2"
    text = re.sub(r"^(\S*?[A-Za-z])1(?=[a-z])", r"\1l", text)  # one for "l": "i1ote"
    text = re.sub(r"^j([^\s!]{1,30}!)", r"¡\1", text)  # "jaca!" -> "¡aca!"
    m = HEAD_RE.match(text)
    if not m:
        return None
    head = m.group("head").strip()
    # "comodidoso, sa" -> headword "comodidoso", feminine ending "sa"
    head, _, fem = (p.strip() for p in head.partition(","))
    # "alversidad / alversidá", "¡hijoé! o ¡hijué!" -> two spellings of the same word
    forms = [f.strip() for f in re.split(r"\s*/\s*|\s+o\s+(?=[¡¿])", head) if f.strip()]
    if not forms:
        return None
    headword = forms[0]
    entry = {
        "headword": headword,
        "forms": forms,
        "fem": fem or None,
        "etymology": m.group("etym"),
        "page": raw["page"],
        "senses": [],
        "phrases": [],
    }
    parts = SEP_RE.split(text[m.end():])

    tags, definition = take_tags(parts[0])
    entry["tags"] = tags
    if definition:
        entry["senses"].append(definition)

    target = entry  # numbered senses ("// 2.") attach to the latest item
    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue
        num = re.match(r"^\d+\s*\.\s*", part)
        if num:
            tags, definition = take_tags(part[num.end():])
            target["senses"].append(definition if not tags else f"[{' '.join(tags)}] {definition}")
            continue
        # A phrase: text up to the first tag-like abbreviation or period.
        pm = re.match(r"^(?P<phrase>.+?[.?!])\s+(?=(?:" + TAG_ALT + r")(?:\s|$))", part)
        if not pm:
            pm = re.match(r"^(?P<phrase>[^.?!]+[.?!])\s*", part)
        if not pm:
            entry["senses"].append(part)
            continue
        phrase = pm.group("phrase").rstrip(".").strip()
        tags, definition = take_tags(part[pm.end():])
        # Phrases usually omit the headword: "// gallina." under comer = "comer gallina".
        stem = fold(headword)[: max(3, len(headword) - 2)]
        full = phrase if stem in fold(phrase) else f"{headword} {phrase}"
        target = {"phrase": full, "tags": tags, "senses": [definition] if definition else []}
        entry["phrases"].append(target)
    return entry


# ---------- 4. write ----------

def main(pdf_path):
    if LAYOUT_CACHE.exists():
        print(f"1/3 reusing layout from {LAYOUT_CACHE} (delete it to re-read the PDF)", file=sys.stderr)
        raw = json.loads(LAYOUT_CACHE.read_text())
    else:
        print("1/3 reading layout…", file=sys.stderr)
        raw = group_entries(read_columns(pdf_path))
        LAYOUT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        LAYOUT_CACHE.write_text(json.dumps(raw, ensure_ascii=False))
    raw = merge_broken_entries(raw)
    vocab = build_vocab(raw)
    for e in raw:
        e["text"] = join_lines(e["lines"], vocab)

    print("2/3 parsing entries…", file=sys.stderr)
    entries, failed = [], []
    for e in raw:
        parsed = parse_entry(e)
        (entries if parsed else failed).append(parsed or e)

    print("3/3 writing…", file=sys.stderr)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(
        {"source": "Agüero Chaves, Diccionario de costarriqueñismos (OCR import)",
         "entries": entries},
        ensure_ascii=False, indent=1,
    ))
    fail_path = OUT_PATH.with_name("dcaa_failed.txt")
    fail_path.write_text("\n\n".join(f"[p{e['page']}] {e['text']}" for e in failed))
    print(f"{len(entries)} entries -> {OUT_PATH}", file=sys.stderr)
    print(f"{len(failed)} unparsed -> {fail_path}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dcaa.pdf")
