import pytest
import yaml

from crc_memo import vault, views
from tests.test_vault import make_memo

OWNERS = """| Nombre | Lote | Teléfono | Correo | También dicen | Notas |
|---|---|---|---|---|---|
| Doña Rosa | L-14 | +506 8888-0000 | rosa@ejemplo.cr | Rosita | tesorera |
| Marta Solís | | | | Marta | |
"""
OUTSIDERS = """| Nombre | Rol | También dicen |
|---|---|---|
| don Ernesto | ingeniero | |
"""


@pytest.fixture
def root(tmp_path):
    """A published vault (made-up data, no git): one minuta with 4 commitments."""
    path = tmp_path / "vault"
    path.mkdir()
    (path / "Propietarios.md").write_text(OWNERS)
    (path / "Externos.md").write_text(OUTSIDERS)
    vault.publish(make_memo(tmp_path), path)
    return path


def note(root, cid):
    return root / "Compromisos/2026" / f"{cid}.md"


def set_front(path, **values):
    text = path.read_text()
    front, body = text.split("---\n", 2)[1:]
    data = yaml.safe_load(front) | values
    path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n" + body)


# --- reading ----------------------------------------------------------------------------

def test_read_notes(root):
    notes = views.read_notes(root)
    assert [n.id for n in notes] == ["M1-C1", "M1-C2", "M1-C3", "M1-C4"]
    first = notes[0]
    assert (first.minuta, first.fecha, first.responsables, first.plazo, first.estado) == \
        ("M1", "2026-09-27", ["Doña Rosa"], "antes del 15", "abierto")
    assert first.what == "Cotizar la pintura del salón"
    assert first.evidence == "[01:03] ⚠ «cita 01:03»"


def test_read_notes_tolerates_hand_edits(root):
    # Obsidian's style: indented lists, empty values; a single responsable as a string.
    note(root, "M1-C1").write_text("---\nid: M1-C1\nresponsables: Doña Rosa\nestado: Cumplido\n"
                                   "cerrado:\n---\nsin título ni evidencia\n")
    (root / "Compromisos/2026/raro.md").write_text("sin frontmatter")
    notes = {n.id: n for n in views.read_notes(root)}
    c1 = notes["M1-C1"]
    assert (c1.responsables, c1.estado, c1.cerrado, c1.what, c1.evidence) == \
        (["Doña Rosa"], "cumplido", None, "M1-C1", None)
    assert notes["raro"].sort_key == (10**9, 0)  # unparseable ids sort last


# --- the generated views -----------------------------------------------------------------

def test_commitments_index(root):
    set_front(note(root, "M1-C2"), estado="cumplido", cerrado="2026-10-20")
    set_front(note(root, "M1-C3"), estado="cancelado")
    views.build(root)
    text = (root / "Compromisos/README.md").read_text()

    assert text.startswith(views.GENERATED + "\n\n# Compromisos\n\n## Abiertos (2)\n")
    assert "### [Doña Rosa](../Personas/DonaRosa.md)\n- [M1-C1](2026/M1-C1.md) · 2026-09-27 · " \
           "Cotizar la pintura del salón · plazo: antes del 15 — [01:03] ⚠ «cita 01:03»\n" in text
    # The sender "Marta" is a variant of Marta Solís in Propietarios.md: linked by full name.
    assert "### [Marta Solís](../Personas/MartaSolis.md)\n- [M1-C4](2026/M1-C4.md)" in text
    assert "## Cerrados (2)\n\n### 2026\n" in text
    assert "- [M1-C2](2026/M1-C2.md) · 2026-09-27 · cumplido 2026-10-20 · sin asignar · " in text
    assert "· cancelado · Vecinos" not in text and "· cancelado · Quienes reciben el audio · " in text


def test_commitment_without_owner_is_listed_as_unassigned(root):
    set_front(note(root, "M1-C1"), responsables=[])
    views.build(root)
    assert "### sin asignar\n- [M1-C1]" in (root / "Compromisos/README.md").read_text()


def test_minutas_index(root, tmp_path):
    second = make_memo(tmp_path, "otro", sha="bar", memo_date="2026-10-05")
    prose = second / "prose.json"
    prose.write_text(prose.read_text().replace('"meeting_recap": null', '"meeting_recap": false'))
    vault.publish(second, root)
    set_front(note(root, "M1-C1"), estado="cumplido")

    text = (root / "Minutas/README.md").read_text()
    views.build(root)
    text = (root / "Minutas/README.md").read_text()

    assert "| N.º | Fecha | Título | Compromisos abiertos |\n|---|---|---|---|\n" \
           "| [M2](2026/M2-2026-10-05/Minuta.md) | 2026-10-05 | " \
           "Reunión de la Asociación de Vecinos (no es reunión) | 4 de 4 |\n" \
           "| [M1](2026/M1-2026-09-27/Minuta.md) | 2026-09-27 | " \
           "Reunión de la Asociación de Vecinos | 3 de 4 |\n" in text


def test_person_pages(root):
    views.build(root)
    rosa = (root / "Personas/DonaRosa.md").read_text()
    front, body = rosa.split("---\n", 2)[1:]
    assert yaml.safe_load(front) == {"aliases": ["Rosita"], "tipo": "propietario", "lote": "L-14",
                                     "tags": ["persona"]}
    assert "<!-- generado por crc_memo: edite Propietarios.md, se reescribe solo -->" in body
    assert "# Doña Rosa\n\n**Lote:** L-14 · **Teléfono:** +506 8888-0000 · " \
           "**Correo:** rosa@ejemplo.cr\n\ntesorera\n" in body
    assert "## Compromisos\n- [M1-C1](../Compromisos/2026/M1-C1.md) · abierto · Cotizar" in body
    assert "## Aparece en\n- [M1](../Minutas/2026/M1-2026-09-27/Minuta.md) · 2026-09-27 · " \
           "Reunión de la Asociación de Vecinos (" in body

    ernesto = (root / "Personas/DonErnesto.md").read_text()
    assert "rol: ingeniero" in ernesto and "edite Externos.md" in ernesto
    assert "## Compromisos" not in ernesto and "## Aparece en" not in ernesto  # never mentioned
    marta = (root / "Personas/MartaSolis.md").read_text()
    assert "lote: null" in marta and "**" not in marta.split("# Marta Solís")[1].split("##")[0]


def test_mentions_ignore_quotes_and_frontmatter():
    text = "---\nrelato_de: Rosa\n---\nRosa dijo «Rosa, Rosa» y rosa."
    assert views._mentions("Rosa", text) == 2


def test_build_is_idempotent_removes_stale_pages_and_skips_busy_files(root):
    changed, _ = views.build(root)
    assert views.build(root) == ([], [])  # nothing left to change

    (root / "Propietarios.md").write_text(OWNERS.replace("| Marta Solís | | | | Marta | |\n", ""))
    (root / "Personas/Notas.md").write_text("una nota mía")  # not generated: kept
    changed, _ = views.build(root)
    assert root / "Personas/MartaSolis.md" in changed and not (root / "Personas/MartaSolis.md").exists()
    assert (root / "Personas/Notas.md").exists()

    busy = {root / "Compromisos/README.md"}
    set_front(note(root, "M1-C1"), estado="cumplido")
    changed, skipped = views.build(root, busy)
    assert skipped == list(busy) and root / "Compromisos/README.md" not in changed


def test_update_and_publish_rebuild_the_views(root, tmp_path):
    set_front(note(root, "M1-C1"), estado="cumplido", cerrado="2026-10-01")
    result = vault.update(root)
    assert root / "Compromisos/README.md" in result.changed
    assert "## Cerrados (1)" in (root / "Compromisos/README.md").read_text()


# --- check ------------------------------------------------------------------------------

def messages(root):
    return [(p.show(root), p.warning) for p in views.check(root).problems]


def warning_of(found, file, message):
    """Is there a problem in `file` (any line) ending with `message`? Returns its warning flag."""
    (flag,) = [w for m, w in found.items() if m.startswith(file + ":") and m.endswith(message)]
    return flag


def test_a_clean_vault_has_only_the_expected_warnings(root):
    # The made-up minuta assigns commitments to roles; "Marta" is the sender's short name.
    assert views.check(root).errors == []


def test_check_tables(root):
    (root / "Propietarios.md").write_text(OWNERS + "| | L-15 | | | | |\n"
                                          "| Doña Rosa | L-16 | 12 | rosa@ | | |\n")
    found = messages(root)
    assert ("Propietarios.md:5: fila sin nombre", False) in found
    assert ("Propietarios.md:6: «Doña Rosa» ya está en Propietarios.md", False) in found
    assert ("Propietarios.md:6: correo no válido: rosa@", False) in found
    assert ("Propietarios.md:6: teléfono no válido: 12", False) in found


def test_check_name_conflict(root):
    (root / "Externos.md").write_text("| Nombre | También dicen |\n|---|---|\n| Rosa Mora | Rosita |\n")
    assert any("«Rosita» is listed for both" in m for m, _ in messages(root))


def test_check_minutas(root, tmp_path):
    minuta = root / "Minutas/2026/M1-2026-09-27/Minuta.md"
    text = minuta.read_text()
    minuta.write_text(text.replace("- **M1-A1** Pintar", "- Pintar")
                          .replace("- **[M1-C2]", "- **[M1-C9]"))
    copy = root / "Minutas/2026/M1-2026-10-01/Minuta.md"  # same number, wrong folder name
    copy.parent.mkdir()
    copy.write_text(text)
    nonumber = root / "Minutas/2026/M7-2026-10-02/Minuta.md"
    nonumber.parent.mkdir()
    nonumber.write_text("# sin encabezado\n")

    found = dict(messages(root))
    line = text.splitlines().index(next(l for l in text.splitlines() if "**M1-A1**" in l)) + 1
    assert any(m.startswith(f"Minutas/2026/M1-2026-09-27/Minuta.md:{line}: punto sin código M1-…: "
                            "- Pintar el salón") for m in found)
    assert any(m.endswith("M1-C9 no tiene nota en Compromisos/") for m in found)
    assert found.get("Compromisos/2026/M1-C2.md:1: M1-C2 no aparece en la minuta M1") is True
    assert "Minutas/2026/M1-2026-10-01/Minuta.md:1: el número M1 también lo usa M1-2026-09-27" in found
    assert "Minutas/2026/M1-2026-10-01/Minuta.md:1: la carpeta debería llamarse M1-2026-09-27" in found
    assert "Minutas/2026/M7-2026-10-02/Minuta.md:1: falta `numero` (un entero) en el encabezado" in found


def test_check_notes(root):
    set_front(note(root, "M1-C1"), id="M1-C9", estado="hecho")
    set_front(note(root, "M1-C2"), estado="cumplido", minuta="M5")
    set_front(note(root, "M1-C3"), responsables=["Fulano"])
    found = dict(messages(root))
    c1, c2, c3 = (f"Compromisos/2026/M1-C{n}.md" for n in (1, 2, 3))
    assert warning_of(found, c1, "`id: M1-C9` no coincide con el archivo M1-C1.md") is False
    assert warning_of(found, c1, "`estado: hecho`: use abierto, cumplido o cancelado") is False
    assert warning_of(found, c2, "está cumplido: falta la fecha en `cerrado`") is True
    assert warning_of(found, c2, "la minuta M5 no existe") is False
    assert warning_of(found, c3, "«Fulano» no está en Propietarios.md ni en Externos.md") is True
    assert "Compromisos/2026/M1-C1.md:2: `id: M1-C9`" in " ".join(found)  # points at its line


def test_check_sorts_problems_by_file_and_line(root):
    set_front(note(root, "M1-C3"), responsables=["Fulano"], estado="?")
    problems = views.check(root).problems
    assert problems == sorted(problems, key=lambda p: (p.path.as_posix(), p.line))


# --- notes follow their minuta ---------------------------------------------------------

def minuta_path(root):
    return root / "Minutas/2026/M1-2026-09-27/Minuta.md"


def edit_minuta(root, old, new):
    path = minuta_path(root)
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new))


def test_parse_commitments(root):
    said = views.parse_commitments(minuta_path(root).read_text())
    assert list(said) == ["M1-C1", "M1-C2", "M1-C3", "M1-C4"]
    assert said["M1-C1"] == views.Said("Doña Rosa", "Cotizar la pintura del salón", "antes del 15")
    assert said["M1-C2"] == views.Said(None, "Hablar con la municipalidad", None)  # sin asignar, sin fecha
    assert said["M1-C3"].owner == "Quienes reciben el audio"  # bold stripped
    text = ("## Compromisos\n- **M2-C1** · Ana · Llamar · al banco\n"  # plain ID, no plazo part
            "## Acuerdos\n- **[M2-C9](x.md)** · No · es · un compromiso\n")
    assert views.parse_commitments(text) == {"M2-C1": views.Said("Ana", "Llamar · al banco", None)}


def test_a_removed_commitment_loses_its_note(root):
    edit_minuta(root, next(l for l in minuta_path(root).read_text().splitlines()
                           if l.startswith("- **[M1-C2]")) + "\n", "")
    updated, removed = views.sync_commitments(root)
    assert removed == [note(root, "M1-C2")] and not note(root, "M1-C2").exists()
    assert updated == []


def test_owner_task_and_plazo_follow_the_minuta(root):
    set_front(note(root, "M1-C1"), estado="cumplido", cerrado="2026-10-01")
    path = note(root, "M1-C1")
    path.write_text(path.read_text() + "- 2026-10-01 · M2 · Ya cotizó\n")
    edit_minuta(root, "· Doña Rosa · Cotizar la pintura del salón · plazo: antes del 15",
                "· Marta Solís · Cotizar pintura y brochas · plazo: el lunes")

    updated, removed = views.sync_commitments(root)

    assert updated == [path] and removed == []
    text = path.read_text()
    front = yaml.safe_load(text.split("---\n")[1])
    assert (front["responsables"], front["plazo"], front["estado"], str(front["cerrado"])) == \
        (["Marta Solís"], "el lunes", "cumplido", "2026-10-01")
    assert "# M1-C1 · Cotizar pintura y brochas\n" in text
    assert "**Responsable:** Marta Solís · **Plazo:** el lunes · **Estado:** cumplido\n" in text
    assert text.endswith("- 2026-10-01 · M2 · Ya cotizó\n")  # follow-ups kept


def test_unchanged_notes_keep_their_formatting(root):
    path = note(root, "M1-C1")
    obsidian = path.read_text().replace("responsables:\n- Doña Rosa", "responsables:\n  - Doña Rosa")
    path.write_text(obsidian)
    views.sync_commitments(root)
    assert path.read_text() == obsidian  # same values: Obsidian's indentation stays


def test_estado_line_follows_the_frontmatter(root):
    set_front(note(root, "M1-C4"), estado="cancelado")
    views.sync_commitments(root)
    assert "**Estado:** cancelado" in note(root, "M1-C4").read_text()


def test_sync_skips_busy_files_and_unnumbered_minutas(root):
    edit_minuta(root, "· Doña Rosa · Cotizar", "· Otra Persona · Cotizar")
    assert views.sync_commitments(root, {minuta_path(root)}) == ([], [])
    assert views.sync_commitments(root, {note(root, "M1-C1")}) == ([], [])
    text = minuta_path(root).read_text()
    minuta_path(root).write_text(text.replace("numero: 1\n", ""))
    assert views.sync_commitments(root) == ([], [])


def test_update_syncs_notes_and_reports_removals(root):
    edit_minuta(root, next(l for l in minuta_path(root).read_text().splitlines()
                           if l.startswith("- **[M1-C2]")) + "\n", "")
    edit_minuta(root, "plazo: antes del 15", "plazo: el viernes")
    result = vault.update(root)
    assert result.removed == [note(root, "M1-C2")]
    assert note(root, "M1-C2") in result.changed and note(root, "M1-C1") in result.changed
    assert "M1-C2" not in (root / "Compromisos/README.md").read_text()



def test_check_cerrado_must_be_a_date(root):
    set_front(note(root, "M1-C1"), estado="cumplido", cerrado="fueron enviadas")
    set_front(note(root, "M1-C2"), estado="cumplido", cerrado="2026-10-01")
    found = dict(messages(root))
    assert warning_of(found, "Compromisos/2026/M1-C1.md",
                      "`cerrado: fueron enviadas` debe ser una fecha AAAA-MM-DD; "
                      "el detalle va en «Seguimiento»") is False
    assert not any(m.startswith("Compromisos/2026/M1-C2.md") for m in found)



@pytest.mark.parametrize("name, key", [("la Asociación de Desarrollo", "asociación de desarrollo"),
                                       ("El desarrollador", "desarrollador"),
                                       ("Laura Mora", "laura mora"), ("los vecinos", "vecinos")])
def test_name_key_ignores_a_leading_article(name, key):
    assert views.name_key(name) == key


def test_an_article_doesnt_make_a_name_unknown(root):
    (root / "Externos.md").write_text(OUTSIDERS + "| Asociación de Desarrollo | institución | |\n")
    set_front(note(root, "M1-C2"), responsables=["la Asociación de Desarrollo"])
    assert not any("Asociación" in m for m, _ in messages(root))
    views.build(root)
    assert "### [la Asociación de Desarrollo](../Personas/AsociacionDeDesarrollo.md)" in \
        (root / "Compromisos/README.md").read_text()
    assert "- [M1-C2]" in (root / "Personas/AsociacionDeDesarrollo.md").read_text()
