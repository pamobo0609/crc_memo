import pytest
import typst

from crc_memo import output, pdf
from tests.test_output import PROSE, minutes


@pytest.fixture
def breve():
    return output.breve_from_minuta(output.render_minuta(minutes(), PROSE, 12))


@pytest.mark.parametrize("text, expected", [
    ("plain", "plain"),
    ("a#b $c *d* _e_ @f <g> [h] `i` ~j k/l = m + n - o \\p",
     "a\\#b \\$c \\*d\\* \\_e\\_ \\@f \\<g\\> \\[h\\] \\`i\\` \\~j k\\/l \\= m \\+ n \\- o \\\\p"),
    ("https://ejemplo.cr", "https:\\/\\/ejemplo.cr"),  # "//" would start a Typst comment
])
def test_escape(text, expected):
    assert pdf.escape(text) == expected


def test_inline_keeps_bold_and_escapes_the_rest():
    assert pdf.inline("**M12-C1** · cuota de **₡5.000** #1") == "*M12\\-C1* · cuota de *₡5.000* \\#1"


def test_to_typst(breve):
    text = pdf.to_typst(breve)
    assert text.startswith("= M12 · Minuta — Reunión de la Asociación de Vecinos\n\n")
    # Header lines keep their line breaks; the last one doesn't need one.
    assert "*Presidió:* Don Carlos \\\n*Relato de:* Marta · audio de 28 min\n" in text
    assert ("#pedido[\n*Piden a quienes reciben el audio:* \\\n"
            "- Enviar la lista de asociados | WhatsApp — *el lunes*\n]") in text
    assert "== Resumen\nLa cuota sube a ₡5.000.\n" in text
    assert "- *M12\\-C1* · Doña Rosa · Cotizar la pintura del salón · plazo: antes del 15\n" in text
    assert text.endswith("#pie[Minuta elaborada automáticamente a partir del relato de Marta; "
                         "no es un acta oficial.]\n")
    assert "<!--" not in text and "---" not in text


def test_to_typst_minimal():
    assert pdf.to_typst("# Minuta — x\n") == "= Minuta — x\n"  # no footer, no frontmatter
    assert pdf.to_typst("> **Piden a todos:**\n") == "#pedido[\n*Piden a todos:* \\\n]\n"
    assert pdf.to_typst("Texto suelto\n\n---\n*Pie uno*\n*Pie dos*\n") == \
        "Texto suelto\n\n#pie[Pie uno \\\nPie dos]\n"


def test_source_uses_the_template_and_an_escaped_title(breve):
    source = pdf.source(breve.replace("titulo: Reunión de la Asociación de Vecinos",
                                      'titulo: Dice "hola" \\ adiós'))
    assert source.startswith('#import "minuta.typ": minuta, pedido, pie\n'
                             '#show: minuta.with(title: "Dice \\"hola\\" \\\\ adiós")\n\n= M12')
    assert pdf.source("sin frontmatter").startswith(
        '#import "minuta.typ": minuta, pedido, pie\n#show: minuta.with(title: "Minuta")')


def test_render_is_a_deterministic_pdf(breve):
    data = pdf.render(breve)
    assert data.startswith(b"%PDF-") and data == pdf.render(breve)


def test_render_treats_warnings_as_errors(monkeypatch, breve):
    monkeypatch.setattr(typst, "compile_with_warnings",
                        lambda *a, **k: (b"%PDF", ["unknown font family: nope"]))
    with pytest.raises(pdf.PdfError, match="Typst warned: unknown font family: nope"):
        pdf.render(breve)


def test_render_reports_typst_errors(monkeypatch, breve):
    monkeypatch.setattr(pdf, "source", lambda breve: "#nada_definido")
    with pytest.raises(pdf.PdfError, match="Typst couldn't build the PDF"):
        pdf.render(breve)


def test_write_only_when_the_bytes_change(tmp_path):
    minuta = tmp_path / "Minuta.md"
    minuta.write_text(output.render_minuta(minutes(), PROSE, 3))
    path = pdf.write(minuta)
    assert path == tmp_path / "Minuta.pdf" and path.read_bytes().startswith(b"%PDF-")
    stamp = path.stat().st_mtime_ns
    pdf.write(minuta)
    assert path.stat().st_mtime_ns == stamp  # identical: not rewritten
