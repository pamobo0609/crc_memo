"""The vault: a private git repo of plain markdown, readable on GitHub and in Obsidian.

Layout (see docs/ROADMAP.md, Phase 4):
    Minutas/<YYYY>/M12-2026-09-27/Minuta.md         the minuta (humans may correct it)
    Minutas/<YYYY>/M12-2026-09-27/Transcripcion.md  the evidence every [mm:ss] points to
    Compromisos/<YYYY>/M12-C3.md                    one living note per commitment

Rules that keep it traceable:
- Minutas get sequential human numbers (M12), like an association's actas; items get
  M12-C3. A number is assigned once and never reused.
- File names are plain ASCII PascalCase, no spaces (file_name()); text inside keeps accents.
- Files humans own (a published Minuta.md, commitment notes) are never overwritten silently.
- Output is deterministic: same input, same bytes. Git is the clock (no times in files).
"""

import hashlib
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from crc_memo import config, ingest, output, summarize
from crc_memo.schemas import Minutes, MinutesCommitment, Prose

VAULT_ENV = "CRC_MEMO_VAULT"
# The vault is in Spanish: folders, file names, frontmatter keys and labels, whatever the
# memo's language (the prose stays as written).
VAULT_LANGUAGE = "es"
CONTACTS_NAME = "Contactos.md"
PEOPLE_DIR = "Personas"
# Obsidian settings for a new vault: markdown links with relative paths (Obsidian's default is
# [[wikilinks]], which GitHub doesn't render), kept up to date when files move.
OBSIDIAN_APP = """{
  "useMarkdownLinks": true,
  "newLinkFormat": "relative",
  "alwaysUpdateLinks": true
}
"""
MINUTAS_DIR = "Minutas"
COMPROMISOS_DIR = "Compromisos"
TRANSCRIPT_NAME = "Transcripcion.md"
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


class VaultError(Exception):
    """Something the user can act on (vault not set, hand-edited minuta, push failed, ...)."""


@dataclass
class PublishResult:
    number: int
    minuta: Path
    created: list[Path] = field(default_factory=list)  # commitment notes written this time
    committed: bool = False
    pushed: bool = False
    warning: str | None = None


# --- names and paths ------------------------------------------------------------------

def file_name(text: str) -> str:
    """'doña Rosa' -> 'DonaRosa', 'el ingeniero del ICE' -> 'ElIngenieroDelICE'.
    Plain ASCII PascalCase: no accents, no spaces, safe on every OS and on GitHub."""
    ascii_text = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", ascii_text)
    return "".join(w[:1].upper() + w[1:] for w in words)


def minuta_dir(vault: Path, number: int, memo_date: str) -> Path:
    return vault / MINUTAS_DIR / memo_date[:4] / f"M{number}-{memo_date}"


def commitment_path(vault: Path, cid: str, memo_date: str) -> Path:
    return vault / COMPROMISOS_DIR / memo_date[:4] / f"{cid}.md"


def vault_dir() -> Path:
    """The local clone of the vault repo, from $CRC_MEMO_VAULT (not in config.py: the
    crc_memo repo is public, the vault's location is personal)."""
    value = os.environ.get(VAULT_ENV)
    if not value:
        raise VaultError(f"Set {VAULT_ENV} to your vault folder, e.g. "
                         f"export {VAULT_ENV}=~/Documents/MinutasVault")
    path = Path(value).expanduser()
    if not path.is_dir():
        raise VaultError(f"{VAULT_ENV}={value} is not a folder. Create one with: memo vault init PATH")
    return check_outside_project(path)


def check_outside_project(path: Path) -> Path:
    """crc_memo is a public repo: a vault inside it could get committed and pushed with it."""
    project = config.PROJECT_DIR.resolve()
    if path.resolve() == project or project in path.resolve().parents:
        raise VaultError(f"The vault can't be inside crc_memo ({project}): this repo is public. "
                         "Put it somewhere else, e.g. ~/Documents/MinutasVault")
    return path


# --- reading ------------------------------------------------------------------------

def read_frontmatter(path: Path) -> dict:
    """The YAML frontmatter of a markdown file ({} if it has none or it's not valid YAML)."""
    match = FRONTMATTER_RE.match(path.read_text())
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def published_minutas(vault: Path) -> list[tuple[Path, dict]]:
    """Every Minuta.md in the vault with its frontmatter, in path order."""
    return [(path, read_frontmatter(path))
            for path in sorted((vault / MINUTAS_DIR).glob(f"*/*/{output.MINUTA_NAME}"))]


def next_number(vault: Path) -> int:
    """One more than the highest number ever used. Gaps (deleted minutas) are never refilled,
    so a number always means the same minuta."""
    numbers = [fm.get("numero") for _, fm in published_minutas(vault)]
    return max([n for n in numbers if isinstance(n, int)], default=0) + 1


def find_by_sha(vault: Path, audio_sha256: str | None) -> tuple[Path, dict] | None:
    """The published minuta of this audio, if any: republishing keeps its number."""
    if not audio_sha256:
        return None
    return next(((p, fm) for p, fm in published_minutas(vault)
                 if fm.get("audio_sha256") == audio_sha256), None)


# --- writing ------------------------------------------------------------------------

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def render_transcript(folder: Path, number: int, minutes: Minutes) -> str:
    """Transcripcion.md: Whisper's lines (packed like the LLM saw them), one per [mm:ss]."""
    header = output.dump_frontmatter({"numero": number, "fecha": output.yaml_date(minutes.source.memo_date),
                                      "memo_id": minutes.provenance and minutes.provenance.memo_id,
                                      "tags": ["transcripcion"]})
    lines = [f"[{summarize.format_timestamp(s.start)}] {s.text}"
             for s in summarize.load_segments(folder)]
    return f"{header}\n# M{number} · Transcripción\n\n" + "\n\n".join(lines) + "\n"


def render_commitment(c: MinutesCommitment, m: Minutes, number: int) -> str:
    """A commitment's living note: what was said (with evidence) + status + follow-ups."""
    labels = output.labels_for(VAULT_LANGUAGE)
    cid = output.item_id(c.id, number)
    owner = output.owner_name(c, m, labels)
    memo_date = m.source.memo_date
    head = output.dump_frontmatter({
        "id": cid, "minuta": f"M{number}", "fecha": output.yaml_date(memo_date),
        "responsables": [owner] if c.owner != "nobody" else [],
        "plazo": c.due, "estado": "abierto", "cerrado": None, "tags": ["compromiso"],
    })
    folder = f"M{number}-{memo_date}"
    evidence = "\n".join(f"- {output.evidence_text(e)}" for e in c.evidence)
    return (f"{head}\n# {cid} · {c.what}\n\n"
            f"**Responsable:** {owner} · **Plazo:** {c.due or labels['no_due']} · "
            f"**Estado:** abierto\n\n"
            f"Dicho en la [minuta M{number}](../../{MINUTAS_DIR}/{memo_date[:4]}/{folder}/"
            f"{output.MINUTA_NAME}):\n{evidence}\n\n"
            f"## Seguimiento\n"
            f"<!-- Agregue una línea por novedad: - AAAA-MM-DD · M13 · qué pasó. "
            f"Al cerrarlo, cambie estado (cumplido / cancelado) y cerrado: AAAA-MM-DD. -->\n")


def _memo_date(folder: Path, minutes: Minutes) -> str:
    """The minuta's date: the audio's (--date or WhatsApp name), else the day it was ingested."""
    if minutes.source.memo_date:
        return minutes.source.memo_date
    return ingest.read_meta(folder).get("ingested_at", date.today().isoformat())[:10]


def publish(folder: Path, vault: Path, force: bool = False, push: bool = True) -> PublishResult:
    """Write a memo's minuta, transcript and commitment notes into the vault, then commit (and
    push). Republishing keeps the minuta's number; a hand-edited Minuta.md is only replaced
    with `force`; existing commitment notes are never touched (they hold follow-ups)."""
    minutes, prose = output.load(folder)
    sha = minutes.provenance and minutes.provenance.audio_sha256
    existing = find_by_sha(vault, sha)
    number = existing[1]["numero"] if existing else next_number(vault)
    memo_date = _memo_date(folder, minutes)
    minutes.source.memo_date = memo_date

    target = minuta_dir(vault, number, memo_date) / output.MINUTA_NAME
    meta = ingest.read_meta(folder)
    if existing:
        edited = _sha(existing[0].read_text()) != meta.get("published", {}).get("sha256")
        if edited and not force:
            raise VaultError(f"{existing[0]} was edited after it was published (or published "
                             "from elsewhere). Use --force to replace it; git keeps the old one.")
        if existing[0] != target:  # the date changed: move it, keeping its number
            for old in [existing[0], existing[0].parent / TRANSCRIPT_NAME]:
                old.unlink(missing_ok=True)
            if not any(existing[0].parent.iterdir()):
                existing[0].parent.rmdir()

    text = output.render_minuta(minutes, prose, number, language=VAULT_LANGUAGE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    (target.parent / TRANSCRIPT_NAME).write_text(render_transcript(folder, number, minutes))
    created = []
    for c in minutes.commitments:
        note = commitment_path(vault, output.item_id(c.id, number), memo_date)
        if not note.exists():
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(render_commitment(c, minutes, number))
            created.append(note)
    ingest.update_meta(folder, published={"number": number, "path": str(target.relative_to(vault)),
                                          "sha256": _sha(text)})

    result = PublishResult(number, target, created)
    commit_and_push(vault, f"M{number} — minuta del {memo_date}", push, result)
    return result


# --- a new vault ----------------------------------------------------------------------

VAULT_README = """# Minutas

Minutas de reuniones, generadas con [crc_memo](https://github.com/pamobo0609/crc_memo) a partir
de audios de WhatsApp y revisadas por personas. **Repositorio privado.**

- `Minutas/<año>/M12-<fecha>/Minuta.md`: la minuta. Cada punto tiene un código (M12-C3) y la
  cita exacta con el minuto del audio donde se dijo: [03:45] «…». ⚠ = cita no encontrada en la
  transcripción: revisar. `Transcripcion.md` al lado es la evidencia.
- `Compromisos/<año>/M12-C3.md`: un archivo por compromiso. Para darle seguimiento, agregue
  líneas en «Seguimiento» y cambie `estado` (abierto / cumplido / cancelado).
- `Contactos.md`: propietarios por lote, con teléfono y correo.
- `Personas/`: una nota por persona; en `aliases` van las formas en que la mencionan
  (doña Rosa, Rosita), así Obsidian la encuentra con cualquiera de ellas.

Para corregir una minuta, edite su `Minuta.md`: el historial de git guarda quién cambió qué.

## Buscar en Obsidian
- `"M12-C3"`: un punto exacto, en la minuta y en su nota de compromiso.
- `[estado:abierto]`: compromisos abiertos. `[responsables:"doña Rosa"]`: los de una persona.
- `tag:#minuta`, `tag:#compromiso`: solo minutas o solo compromisos.
- `path:Minutas/2026 cuota`: la palabra «cuota» en las minutas de 2026.
"""

GITIGNORE = "# PDFs are regenerated from Minuta.md\n*.pdf\n.DS_Store\n.obsidian/workspace*.json\n"

CONTACTS_TEMPLATE = """# Contactos

Una fila por lote. Varios propietarios (una pareja), teléfonos o correos: separados por `;`.

| Lote | Propietarios | Teléfono | Correo | Notas |
|---|---|---|---|---|
"""


def init(path: Path) -> list[Path]:
    """Create an empty vault: folders, README, .gitignore, contact and alias templates, and a
    git repo. Never overwrites a file that exists; returns the files it created."""
    check_outside_project(path)
    files = {path / "README.md": VAULT_README, path / ".gitignore": GITIGNORE,
             path / CONTACTS_NAME: CONTACTS_TEMPLATE,
             path / ".obsidian" / "app.json": OBSIDIAN_APP}
    created = []
    for file, text in files.items():
        if not file.exists():
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text)
            created.append(file)
    try:
        _git(path, "rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.CalledProcessError):
        subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    return created


# --- git ----------------------------------------------------------------------------

def _git(vault: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(vault), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def commit_and_push(vault: Path, message: str, push: bool, result: PublishResult) -> None:
    """Commit everything the tool wrote, then push to the vault's upstream unless told not to.
    A vault that isn't a git repo just keeps the files (with a warning)."""
    try:
        _git(vault, "rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.CalledProcessError):
        result.warning = f"{vault} is not a git repo: files written, nothing committed."
        return
    _git(vault, "add", "--all", "--", MINUTAS_DIR, COMPROMISOS_DIR)
    if _git(vault, "diff", "--cached", "--name-only"):
        _git(vault, "commit", "--quiet", "-m", message)
        result.committed = True
    if not push:
        return
    try:
        _git(vault, "push", "--quiet")
    except subprocess.CalledProcessError as e:
        raise VaultError(f"Committed locally, but the push failed: {e.stderr.strip()}") from None
    result.pushed = True
