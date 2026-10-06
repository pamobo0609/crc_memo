"""Views generated from the vault, and its checks.

Generated (rewritten on every `memo vault update` / `memo publish`; never edit them):
    Minutas/README.md       every minuta, newest first, with its open commitments
    Compromisos/README.md   open commitments by person, then closed ones by year
    Personas/<Name>.md      one page per person in Propietarios.md / Externos.md, with Obsidian
                            `aliases` (how the audios call them) so search finds every form

They're built from what humans edit: the commitment notes (status lives there), the minutas,
and the two name tables. Output is deterministic: dates, never "12 days ago" (that would
change every day), stable sort orders.

`check()` validates the files humans edit and reports problems as file:line.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from crc_memo import output, vault

GENERATED = "<!-- generado por crc_memo: no editar, se reescribe solo -->"
STATES = {"abierto", "cumplido", "cancelado"}
INDEX_NAME = "README.md"
ITEM_SECTIONS = {"Acuerdos", "Compromisos", "Pendientes", "Observaciones"}  # vault labels (es)
ID_RE = re.compile(r"^M(\d+)-([ACPO])(\d+)$")
EVIDENCE_LINE_RE = re.compile(r"^- (\[\d{1,2}:\d{2}(?::\d{2})?\].*)$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[\d][\d \-]{6,}$")


@dataclass
class Note:
    """A commitment note (Compromisos/<YYYY>/M12-C3.md)."""
    path: Path
    id: str
    minuta: str
    fecha: str
    responsables: list[str]
    plazo: str | None
    estado: str
    cerrado: str | None
    what: str
    evidence: str | None  # the first "[mm:ss] «…»" line

    @property
    def sort_key(self) -> tuple:
        match = ID_RE.match(self.id)
        return (int(match[1]), int(match[3])) if match else (10**9, 0)


@dataclass
class MinutaInfo:
    path: Path
    numero: int | None
    fecha: str
    titulo: str
    es_reunion: bool | None
    text: str


@dataclass
class Person:
    name: str
    kind: str  # "propietario" | "externo"
    row: dict[str, str]
    variants: list[str]

    @property
    def file(self) -> str:
        return vault.file_name(self.name) + ".md"


def _str(value) -> str:
    return "" if value is None else str(value)


# --- reading ------------------------------------------------------------------------

def read_notes(root: Path) -> list[Note]:
    notes = []
    for path in sorted((root / vault.COMPROMISOS_DIR).glob("*/*.md")):
        front, body = output.split_frontmatter(path.read_text())
        title = next((line for line in body.splitlines() if line.startswith("# ")), "")
        evidence = next((m[1] for m in map(EVIDENCE_LINE_RE.match, body.splitlines()) if m), None)
        responsables = front.get("responsables") or []
        notes.append(Note(
            path=path, id=_str(front.get("id")) or path.stem, minuta=_str(front.get("minuta")),
            fecha=_str(front.get("fecha")),
            responsables=[_str(r) for r in (responsables if isinstance(responsables, list)
                                            else [responsables])],
            plazo=front.get("plazo") and _str(front.get("plazo")),
            estado=_str(front.get("estado")).strip().lower(),
            cerrado=front.get("cerrado") and _str(front.get("cerrado")),
            what=title.split(" · ", 1)[-1].strip() if title else path.stem,
            evidence=evidence,
        ))
    return sorted(notes, key=lambda n: n.sort_key)


def read_minutas(root: Path) -> list[MinutaInfo]:
    minutas = []
    for path, front in vault.published_minutas(root):
        numero = front.get("numero")
        minutas.append(MinutaInfo(path, numero if isinstance(numero, int) else None,
                                  _str(front.get("fecha")), _str(front.get("titulo")),
                                  front.get("es_reunion"), path.read_text()))
    return minutas


def read_people(root: Path) -> list[Person]:
    people = []
    for file, kind in [(vault.OWNERS_NAME, "propietario"), (vault.OUTSIDERS_NAME, "externo")]:
        for row in vault.read_table(root / file):
            name = row.get("nombre", "").strip()
            if name:
                variants = [v.strip() for v in row.get("tambien dicen", "").split(";") if v.strip()]
                people.append(Person(name, kind, row, variants))
    return people


# --- rendering ------------------------------------------------------------------------

def _person_link(name: str, people: dict[str, Person], prefix: str) -> str:
    person = people.get(name.lower())
    return f"[{name}]({prefix}{vault.PEOPLE_DIR}/{person.file})" if person else name


def _note_line(note: Note, prefix: str, extra: str = "") -> str:
    link = f"[{note.id}]({prefix}{note.path.parent.name}/{note.path.name})"
    plazo = f" · plazo: {note.plazo}" if note.plazo else ""
    evidence = f" — {note.evidence}" if note.evidence else ""
    return f"- {link} · {note.fecha}{extra} · {note.what}{plazo}{evidence}"


def render_commitments_index(notes: list[Note], people: dict[str, Person]) -> str:
    """Compromisos/README.md: open commitments grouped by person, then closed ones by year."""
    labels = output.labels_for(vault.VAULT_LANGUAGE)
    open_notes = [n for n in notes if n.estado not in STATES - {"abierto"}]
    by_person: dict[str, list[Note]] = {}
    for note in open_notes:
        for name in note.responsables or [labels["unassigned"]]:
            by_person.setdefault(name, []).append(note)
    lines = [GENERATED, "", "# Compromisos", "",
             f"## Abiertos ({len(open_notes)})"]
    for name in sorted(by_person, key=str.casefold):
        lines += ["", f"### {_person_link(name, people, '../')}"]
        lines += [_note_line(n, "") for n in by_person[name]]
    closed = [n for n in notes if n.estado in STATES - {"abierto"}]
    if closed:
        lines += ["", f"## Cerrados ({len(closed)})"]
        for year in sorted({n.path.parent.name for n in closed}, reverse=True):
            lines += ["", f"### {year}"]
            lines += [_note_line(n, "", f" · {n.estado}" + (f" {n.cerrado}" if n.cerrado else "")
                                 + " · " + (", ".join(n.responsables) or labels["unassigned"]))
                      for n in closed if n.path.parent.name == year]
    return "\n".join(lines) + "\n"


def render_minutas_index(minutas: list[MinutaInfo], notes: list[Note]) -> str:
    """Minutas/README.md: every minuta, newest first, with how many commitments are open."""
    lines = [GENERATED, "", "# Minutas", "",
             "| N.º | Fecha | Título | Compromisos abiertos |", "|---|---|---|---|"]
    for m in sorted(minutas, key=lambda m: (m.fecha, m.numero or 0), reverse=True):
        mine = [n for n in notes if n.minuta == f"M{m.numero}"]
        still_open = sum(n.estado not in STATES - {"abierto"} for n in mine)
        title = (m.titulo or "—") + (" (no es reunión)" if m.es_reunion is False else "")
        link = f"[M{m.numero}]({m.path.relative_to(m.path.parents[2]).as_posix()})"
        lines.append(f"| {link} | {m.fecha} | {title.replace('|', '/')} | "
                     f"{still_open} de {len(mine)} |")
    return "\n".join(lines) + "\n"


def _mentions(name: str, text: str) -> int:
    """How often `name` appears in a minuta, outside the «quotes» (those are as said)."""
    outside = vault.QUOTE_RE.sub("", output.split_frontmatter(text)[1])
    return len(re.findall(r"(?<!\w)" + re.escape(name) + r"(?!\w)", outside, re.IGNORECASE))


def render_person(person: Person, notes: list[Note], minutas: list[MinutaInfo]) -> str:
    """Personas/<Name>.md: who they are, their commitments, the minutas that mention them."""
    row = person.row
    front = {"aliases": person.variants, "tipo": person.kind}
    if person.kind == "propietario":
        front["lote"] = row.get("lote") or None
    else:
        front["rol"] = row.get("rol") or None
    front["tags"] = ["persona"]
    source = vault.OWNERS_NAME if person.kind == "propietario" else vault.OUTSIDERS_NAME
    details = [(label, row.get(key, "")) for label, key in
               [("Lote", "lote"), ("Rol", "rol"), ("Teléfono", "telefono"), ("Correo", "correo")]]
    lines = [GENERATED.replace("no editar", f"edite {source}"), "", f"# {person.name}", ""]
    shown = " · ".join(f"**{label}:** {value}" for label, value in details if value)
    lines += [shown] if shown else []
    if row.get("notas"):
        lines += ["", row["notas"]]
    mine = [n for n in notes if person.name.lower() in (r.lower() for r in n.responsables)]
    if mine:
        lines += ["", "## Compromisos"]
        lines += [f"- [{n.id}](../{vault.COMPROMISOS_DIR}/{n.path.parent.name}/{n.path.name}) · "
                  f"{n.estado or '?'} · {n.what}" for n in mine]
    seen = [(m, _mentions(person.name, m.text)) for m in sorted(minutas, key=lambda m: m.fecha)]
    seen = [(m, count) for m, count in seen if count]
    if seen:
        lines += ["", "## Aparece en"]
        lines += [f"- [M{m.numero}](../{m.path.relative_to(m.path.parents[3]).as_posix()}) · "
                  f"{m.fecha} · {m.titulo} ({count})" for m, count in seen]
    return output.dump_frontmatter(front) + "\n" + "\n".join(lines) + "\n"


# --- writing ------------------------------------------------------------------------

def build(root: Path, busy: set[Path] = frozenset()) -> tuple[list[Path], list[Path]]:
    """Rewrite every generated view. Returns (changed or removed files, skipped files).
    Files with uncommitted edits are skipped like everywhere else; person pages for people
    no longer in the tables are removed."""
    notes, minutas, people = read_notes(root), read_minutas(root), read_people(root)
    by_name = {p.name.lower(): p for p in people}
    wanted = {
        root / vault.MINUTAS_DIR / INDEX_NAME: render_minutas_index(minutas, notes),
        root / vault.COMPROMISOS_DIR / INDEX_NAME: render_commitments_index(notes, by_name),
    }
    for person in people:
        wanted[root / vault.PEOPLE_DIR / person.file] = render_person(person, notes, minutas)
    changed, skipped = [], []
    for path, text in wanted.items():
        if path in busy:
            skipped.append(path)
        elif not path.exists() or path.read_text() != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            changed.append(path)
    for stale in sorted((root / vault.PEOPLE_DIR).glob("*.md")):
        if stale not in wanted and stale not in busy and \
                "<!-- generado por crc_memo" in stale.read_text():
            stale.unlink()
            changed.append(stale)
    return changed, skipped


# --- checking -----------------------------------------------------------------------

@dataclass
class Problem:
    path: Path
    line: int
    message: str
    warning: bool = False  # True: worth a look; False: something is wrong

    def show(self, root: Path) -> str:
        return f"{self.path.relative_to(root).as_posix()}:{self.line}: {self.message}"


@dataclass
class CheckResult:
    problems: list[Problem] = field(default_factory=list)

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if not p.warning]


def _line_of(text: str, needle: str) -> int:
    return next((n for n, line in enumerate(text.splitlines(), 1) if needle in line), 1)


def _check_minutas(minutas: list[MinutaInfo], notes: list[Note], out: list[Problem]) -> None:
    numbers: dict[int, Path] = {}
    for m in minutas:
        if m.numero is None:
            out.append(Problem(m.path, 1, "falta `numero` (un entero) en el encabezado"))
            continue
        if m.numero in numbers:
            out.append(Problem(m.path, 1, f"el número M{m.numero} también lo usa "
                                          f"{numbers[m.numero].parent.name}"))
        numbers[m.numero] = m.path
        if m.path.parent.name != f"M{m.numero}-{m.fecha}":
            out.append(Problem(m.path, 1, f"la carpeta debería llamarse M{m.numero}-{m.fecha}"))
        body = output.split_frontmatter(m.text)[1]
        first_line = m.text[:len(m.text) - len(body)].count("\n") + 1  # after the frontmatter
        section, ids = None, set()
        for n, line in enumerate(body.splitlines(), first_line):
            if line.startswith("## "):
                section = line[3:].strip()
            elif section in ITEM_SECTIONS and line.startswith("- "):
                match = re.match(r"^- \*\*\[?(M\d+-[ACPO]\d+)", line)
                if not match or not match[1].startswith(f"M{m.numero}-"):
                    out.append(Problem(m.path, n, f"punto sin código M{m.numero}-…: {line[:60]}"))
                else:
                    ids.add(match[1])
        notes_here = {note.id for note in notes if note.minuta == f"M{m.numero}"}
        for cid in sorted(i for i in ids if "-C" in i and i not in notes_here):
            out.append(Problem(m.path, _line_of(m.text, cid),
                               f"{cid} no tiene nota en {vault.COMPROMISOS_DIR}/"))
        for cid in sorted(notes_here - ids):
            note = next(note for note in notes if note.id == cid)
            out.append(Problem(note.path, 1, f"{cid} no aparece en la minuta M{m.numero}",
                               warning=True))


def _check_notes(notes: list[Note], minutas: list[MinutaInfo], known: set[str],
                 out: list[Problem]) -> None:
    published = {f"M{m.numero}" for m in minutas}
    for note in notes:
        text = note.path.read_text()
        if note.id != note.path.stem:
            out.append(Problem(note.path, _line_of(text, "id:"),
                               f"`id: {note.id}` no coincide con el archivo {note.path.name}"))
        if note.estado not in STATES:
            out.append(Problem(note.path, _line_of(text, "estado:"),
                               f"`estado: {note.estado}`: use abierto, cumplido o cancelado"))
        elif note.estado != "abierto" and not note.cerrado:
            out.append(Problem(note.path, _line_of(text, "cerrado:"),
                               f"está {note.estado}: falta la fecha en `cerrado`", warning=True))
        if note.minuta not in published:
            out.append(Problem(note.path, _line_of(text, "minuta:"),
                               f"la minuta {note.minuta or '?'} no existe"))
        for name in note.responsables:
            if name.lower() not in known:
                out.append(Problem(note.path, _line_of(text, name),
                                   f"«{name}» no está en {vault.OWNERS_NAME} ni en "
                                   f"{vault.OUTSIDERS_NAME}", warning=True))


def _check_tables(root: Path, out: list[Problem]) -> None:
    seen: dict[str, str] = {}
    for file in [vault.OWNERS_NAME, vault.OUTSIDERS_NAME]:
        path = root / file
        for row in vault.read_table(path):
            line = int(row["_line"])
            name = row.get("nombre", "").strip()
            if not name:
                out.append(Problem(path, line, "fila sin nombre"))
                continue
            if name.lower() in seen:
                out.append(Problem(path, line, f"«{name}» ya está en {seen[name.lower()]}"))
            seen[name.lower()] = file
            for email in filter(None, (e.strip() for e in row.get("correo", "").split(";"))):
                if not EMAIL_RE.match(email):
                    out.append(Problem(path, line, f"correo no válido: {email}"))
            for phone in filter(None, (t.strip() for t in row.get("telefono", "").split(";"))):
                if not PHONE_RE.match(phone):
                    out.append(Problem(path, line, f"teléfono no válido: {phone}"))


def check(root: Path) -> CheckResult:
    """Validate what humans edit: minutas, commitment notes and the name tables."""
    result = CheckResult()
    try:
        known = set(vault.name_map(root))
    except vault.VaultError as e:
        result.problems.append(Problem(root / vault.OUTSIDERS_NAME, 1, str(e)))
        known = set()
    labels = output.labels_for(vault.VAULT_LANGUAGE)
    known |= {labels[k].lower() for k in ["speaker", "recipients", "unassigned"]}
    notes, minutas = read_notes(root), read_minutas(root)
    _check_tables(root, result.problems)
    _check_minutas(minutas, notes, result.problems)
    _check_notes(notes, minutas, known, result.problems)
    result.problems.sort(key=lambda p: (p.path.as_posix(), p.line))
    return result
