// Minuta breve as a PDF for the WhatsApp group: read on phones, often by elderly people.
// Large text, short lines (A5), no timestamps or links. Bundled fonts only, and no date in
// the PDF metadata, so the same minuta always gives the same bytes.

#let minuta(title: "", body) = {
  set document(title: title, date: none)
  set page(paper: "a5", margin: (x: 1.3cm, y: 1.5cm),
           numbering: "1 / 1", number-align: center)
  set text(font: "Libertinus Serif", size: 14pt, lang: "es")
  set par(leading: 0.7em, spacing: 0.9em)
  set list(spacing: 0.8em, indent: 0.2em)
  show heading.where(level: 1): set text(size: 19pt)
  show heading.where(level: 1): set block(below: 1em)
  show heading.where(level: 2): set text(size: 16pt, fill: rgb("#1f4e79"))
  show heading.where(level: 2): set block(above: 1.3em, below: 0.6em)
  body
}

// What the speaker asks of the people receiving the audio: the line nobody should miss.
#let pedido(body) = block(
  width: 100%, inset: 10pt, radius: 3pt, fill: rgb("#fff4d6"),
  stroke: (left: 4pt + rgb("#e0a800")), body)

// "Generated from an audio; not an official acta."
#let pie(body) = {
  v(1em)
  line(length: 100%, stroke: 0.5pt + gray)
  text(size: 11pt, fill: rgb("#555555"), style: "italic", body)
}
