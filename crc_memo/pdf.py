"""The minuta breve as a PDF for the WhatsApp group, compiled locally with Typst.

Why Typst: one Python package (no LaTeX, no browser), free (Apache-2.0), fast, and it runs the
same on macOS and Linux CI. The breve's markdown has a small fixed grammar (headings, bold,
lists, the recipients callout, the footer), so it's converted to Typst here, in code: Typst's
markdown packages would download from the internet at compile time.

Deterministic: bundled fonts only (system fonts differ per machine) and no date in the PDF
metadata, so the same minuta always gives the same bytes. Any Typst warning is an error —
an unknown font, for one, only warns and silently falls back to another.
"""

import re
from pathlib import Path

import typst

from crc_memo import output

TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "minuta.typ"
PDF_NAME = "Minuta.pdf"
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# Characters with a meaning in Typst markup; "/" because "//" starts a comment (URLs).
SPECIAL_RE = re.compile(r"([\\#$*_@<>\[\]`~/=+-])")


class PdfError(Exception):
    """Typst failed or warned (e.g. a missing font): the PDF wouldn't be what we expect."""


def escape(text: str) -> str:
    """Plain text, safe inside Typst markup."""
    return SPECIAL_RE.sub(r"\\\1", text)


def inline(text: str) -> str:
    """One line of breve markdown: **bold** becomes Typst *strong*, everything else escaped."""
    parts = BOLD_RE.split(text)  # odd positions were inside ** **
    return "".join(f"*{escape(part)}*" if i % 2 else escape(part) for i, part in enumerate(parts))


def _is_text(line: str) -> bool:
    return bool(line.strip()) and not line.startswith(("#", "- ", ">", "---", "<!--"))


def to_typst(breve: str) -> str:
    """MinutaBreve.md -> Typst markup (the body that goes inside the template)."""
    front, body = output.split_frontmatter(breve)
    lines = body.splitlines()
    out: list[str] = []
    quote: list[str] = []
    footer: list[str] = []

    def flush_quote() -> None:
        if quote:
            out.append("#pedido[\n" + "\n".join(
                ("- " + inline(q[2:])) if q.startswith("- ") else inline(q) + " \\"
                for q in quote) + "\n]")
            quote.clear()

    for n, line in enumerate(lines):
        if footer or line == "---":  # everything after the rule is the footer
            if line != "---" or footer:
                footer.append(line.strip().strip("*"))
            else:
                footer.append("")
            continue
        if line.startswith("<!--"):
            continue
        if line.startswith(">"):
            quote.append(line[1:].strip())
            continue
        flush_quote()
        if line.startswith("# "):
            out.append("= " + inline(line[2:]))
        elif line.startswith("## "):
            out.append("== " + inline(line[3:]))
        elif line.startswith("- "):
            out.append("- " + inline(line[2:]))
        elif _is_text(line):
            next_line = lines[n + 1] if n + 1 < len(lines) else ""
            out.append(inline(line) + (" \\" if _is_text(next_line) else ""))
        else:
            out.append("")
    flush_quote()
    text = "\n".join(out).strip("\n")
    footer_lines = [inline(f) for f in footer if f]
    if footer_lines:
        text += "\n\n#pie[" + " \\\n".join(footer_lines) + "]"
    return text + "\n"


def source(breve: str) -> str:
    """The whole Typst document: the template applied to the converted breve."""
    title = str(output.split_frontmatter(breve)[0].get("titulo") or "Minuta")
    title = title.replace("\\", "\\\\").replace('"', '\\"')
    return (f'#import "{TEMPLATE_NAME}": minuta, pedido, pie\n'
            f'#show: minuta.with(title: "{title}")\n\n' + to_typst(breve))


def render(breve: str) -> bytes:
    """MinutaBreve.md text -> PDF bytes."""
    try:
        pdf, warnings = typst.compile_with_warnings(
            source(breve).encode(), root=str(TEMPLATES_DIR), ignore_system_fonts=True)
    except typst.TypstError as e:
        raise PdfError(f"Typst couldn't build the PDF: {e}") from None
    if warnings:
        raise PdfError(f"Typst warned: {'; '.join(map(str, warnings))}")
    return pdf


def write(minuta: Path) -> Path:
    """Minuta.pdf next to a Minuta.md, from its breve (so corrections carry over). Only
    rewritten when the bytes change, so it never looks modified for nothing."""
    path = minuta.parent / PDF_NAME
    pdf = render(output.breve_from_minuta(minuta.read_text()))
    if not path.exists() or path.read_bytes() != pdf:
        path.write_bytes(pdf)
    return path
