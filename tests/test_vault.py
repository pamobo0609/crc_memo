import json
import subprocess
from datetime import date

import pytest
import yaml

from crc_memo import vault
from crc_memo.schemas import Provenance, Source
from tests.test_output import PROSE, minutes


@pytest.fixture(autouse=True)
def git_identity(monkeypatch):
    """Commits need an author; CI machines have none configured."""
    for var in ["GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"]:
        monkeypatch.setenv(var, "Test")
    for var in ["GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"]:
        monkeypatch.setenv(var, "test@example.com")


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A vault that is a git repo with an upstream (a local bare repo: no network)."""
    remote, path = tmp_path / "remote.git", tmp_path / "vault"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)
    subprocess.run(["git", "clone", "--quiet", str(remote), str(path)], check=True,
                   capture_output=True)
    git(path, "commit", "--quiet", "--allow-empty", "-m", "init")
    git(path, "push", "--quiet", "-u", "origin", "HEAD")
    return path


def make_memo(tmp_path, name="memo", sha="f00", memo_date="2026-09-27", **changes):
    """A summarized memo folder (made-up data)."""
    folder = tmp_path / name
    folder.mkdir()
    m = minutes(provenance=Provenance(memo_id=name, audio_sha256=sha, audio_name="nota.ogg",
                                      whisper="w", llm="q", prompts="p", code="c"),
                source=Source(sender="Marta", memo_date=memo_date, duration="27:42",
                              language="es"), **changes)
    (folder / "minutes.json").write_text(m.model_dump_json())
    (folder / "prose.json").write_text(json.dumps(PROSE.model_dump()))
    (folder / "meta.json").write_text(json.dumps({"id": name, "ingested_at": "2026-10-01T10:00:00"}))
    (folder / "segments.json").write_text(json.dumps(
        [{"start": 0.0, "end": 12.0, "text": " Buenos días vecinos."},
         {"start": 12.0, "end": 20.0, "text": " Les cuento."}]))
    return folder


# --- names ----------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("doña Rosa", "DonaRosa"), ("el ingeniero del ICE", "ElIngenieroDelICE"),
    ("Transcripción", "Transcripcion"), ("Don Mauro Arias (presidente)", "DonMauroAriasPresidente"),
    ("  ", ""), ("Ñandú 2", "Nandu2"),
])
def test_file_name(text, expected):
    assert vault.file_name(text) == expected


def test_paths(tmp_path):
    assert vault.minuta_dir(tmp_path, 12, "2026-09-27") == tmp_path / "Minutas/2026/M12-2026-09-27"
    assert vault.commitment_path(tmp_path, "M12-C3", "2027-01-02") == \
        tmp_path / "Compromisos/2027/M12-C3.md"


def test_vault_dir(monkeypatch, tmp_path):
    monkeypatch.delenv(vault.VAULT_ENV, raising=False)
    with pytest.raises(vault.VaultError, match="Set CRC_MEMO_VAULT"):
        vault.vault_dir()
    monkeypatch.setenv(vault.VAULT_ENV, str(tmp_path / "nope"))
    with pytest.raises(vault.VaultError, match="is not a folder"):
        vault.vault_dir()
    monkeypatch.setenv(vault.VAULT_ENV, str(tmp_path))
    assert vault.vault_dir() == tmp_path


@pytest.mark.parametrize("text, expected", [
    ("---\nnumero: 3\n---\n# x", {"numero": 3}),
    ("# no frontmatter", {}),
    ("---\nnumero: [\n---\n", {}),       # invalid YAML
    ("---\n- a list\n---\n", {}),         # not a mapping
])
def test_read_frontmatter(tmp_path, text, expected):
    (tmp_path / "x.md").write_text(text)
    assert vault.read_frontmatter(tmp_path / "x.md") == expected


def test_next_number_never_refills_gaps(tmp_path):
    assert vault.next_number(tmp_path) == 1
    for number, folder in [(1, "2026/M1-2026-01-01"), (5, "2026/M5-2026-02-01"),
                           ("x", "2026/Mx-2026-03-01")]:
        path = tmp_path / "Minutas" / folder / "Minuta.md"
        path.parent.mkdir(parents=True)
        path.write_text(f"---\nnumero: {number}\n---\n")
    assert vault.next_number(tmp_path) == 6
    assert vault.find_by_sha(tmp_path, None) is None


# --- publish --------------------------------------------------------------------------

def test_publish_numbers_writes_commits_and_pushes(repo, tmp_path):
    result = vault.publish(make_memo(tmp_path), repo)

    assert (result.number, result.committed, result.pushed, result.warning) == (1, True, True, None)
    folder = repo / "Minutas/2026/M1-2026-09-27"
    assert result.minuta == folder / "Minuta.md"
    text = result.minuta.read_text()
    assert yaml.safe_load(text.split("---\n")[1])["numero"] == 1
    assert "- **[M1-C1](../../../Compromisos/2026/M1-C1.md)** · Doña Rosa" in text
    assert (folder / "MinutaBreve.md").read_text() == \
        vault.output.breve_from_minuta(result.minuta.read_text())
    transcript = (folder / "Transcripcion.md").read_text()
    assert "# M1 · Transcripción\n\n[00:00] Buenos días vecinos.\n\n[00:12] Les cuento.\n" in transcript
    assert sorted(p.name for p in (repo / "Compromisos/2026").iterdir()) == \
        ["M1-C1.md", "M1-C2.md", "M1-C3.md", "M1-C4.md"]
    assert git(repo, "log", "-1", "--format=%s") == "M1 — minuta del 2026-09-27"
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "@{u}")  # pushed

    second = vault.publish(make_memo(tmp_path, "otro", sha="bar", memo_date="2026-10-05"), repo)
    assert second.number == 2


def test_commitment_note(repo, tmp_path):
    vault.publish(make_memo(tmp_path), repo)
    note = (repo / "Compromisos/2026/M1-C1.md").read_text()
    front = yaml.safe_load(note.split("---\n")[1])
    assert "\nfecha: 2026-09-27\n" in note  # unquoted: a Date property in Obsidian
    assert front == {"id": "M1-C1", "minuta": "M1", "fecha": date(2026, 9, 27),
                     "responsables": ["Doña Rosa"], "plazo": "antes del 15", "estado": "abierto",
                     "cerrado": None, "tags": ["compromiso"]}
    assert "# M1-C1 · Cotizar la pintura del salón\n" in note
    assert "Dicho en la [minuta M1](../../Minutas/2026/M1-2026-09-27/Minuta.md):\n" \
           "- [01:03] ⚠ «cita 01:03»\n" in note
    assert "## Seguimiento\n" in note
    nobody = yaml.safe_load((repo / "Compromisos/2026/M1-C2.md").read_text().split("---\n")[1])
    assert nobody["responsables"] == [] and nobody["plazo"] is None


def test_republish_keeps_the_number_and_follow_ups(repo, tmp_path):
    memo = make_memo(tmp_path)
    vault.publish(memo, repo)
    note = repo / "Compromisos/2026/M1-C1.md"
    note.write_text(note.read_text() + "- 2026-10-15 · M2 · Ya cotizó\n")
    git(repo, "commit", "--quiet", "-am", "seguimiento")

    again = vault.publish(memo, repo)

    assert (again.number, again.created, again.committed) == (1, [], False)  # nothing changed
    assert "Ya cotizó" in note.read_text()


def test_republish_refuses_a_hand_edited_minuta(repo, tmp_path):
    memo = make_memo(tmp_path)
    first = vault.publish(memo, repo)
    first.minuta.write_text(first.minuta.read_text().replace("Doña Rosa", "Don Jorge"))

    with pytest.raises(vault.VaultError, match="was edited after it was published"):
        vault.publish(memo, repo)
    assert "Don Jorge" in first.minuta.read_text()

    forced = vault.publish(memo, repo, force=True)
    assert forced.number == 1 and "Don Jorge" not in forced.minuta.read_text()


def test_published_from_elsewhere_counts_as_edited(repo, tmp_path):
    memo = make_memo(tmp_path)
    vault.publish(memo, repo)
    meta = json.loads((memo / "meta.json").read_text())
    del meta["published"]
    (memo / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(vault.VaultError):
        vault.publish(memo, repo)


def test_date_change_moves_the_minuta_and_keeps_its_number(repo, tmp_path):
    memo = make_memo(tmp_path)
    vault.publish(memo, repo)
    m = json.loads((memo / "minutes.json").read_text())
    m["source"]["memo_date"] = "2026-09-28"
    (memo / "minutes.json").write_text(json.dumps(m))

    moved = vault.publish(memo, repo)

    assert moved.minuta == repo / "Minutas/2026/M1-2026-09-28/Minuta.md"
    assert (moved.minuta.parent / "MinutaBreve.md").exists()
    assert not (repo / "Minutas/2026/M1-2026-09-27").exists()


def test_move_keeps_other_files_in_the_old_folder(repo, tmp_path):
    memo = make_memo(tmp_path)
    first = vault.publish(memo, repo)
    (first.minuta.parent / "Notas.md").write_text("de un humano")
    m = json.loads((memo / "minutes.json").read_text())
    m["source"]["memo_date"] = "2026-09-28"
    (memo / "minutes.json").write_text(json.dumps(m))
    vault.publish(memo, repo)
    assert (first.minuta.parent / "Notas.md").exists() and not first.minuta.exists()


def test_without_audio_date_uses_the_ingest_date(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = vault.publish(make_memo(tmp_path, memo_date=None), plain)
    assert result.minuta.parent.name == "M1-2026-10-01"


def test_not_a_git_repo_just_writes_files(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = vault.publish(make_memo(tmp_path), plain)
    assert result.minuta.exists() and not result.committed
    assert "not a git repo" in result.warning


def test_no_push(repo, tmp_path):
    result = vault.publish(make_memo(tmp_path), repo, push=False)
    assert (result.committed, result.pushed) == (True, False)
    assert git(repo, "rev-parse", "HEAD") != git(repo, "rev-parse", "@{u}")


def test_push_failure_keeps_the_local_commit(repo, tmp_path):
    git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(vault.VaultError, match="Committed locally, but the push failed"):
        vault.publish(make_memo(tmp_path), repo)
    assert git(repo, "log", "-1", "--format=%s") == "M1 — minuta del 2026-09-27"



# --- Spanish, outside the project, init ----------------------------------------------

def test_the_vault_is_in_spanish_whatever_the_memo_language(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    memo = make_memo(tmp_path)
    m = json.loads((memo / "minutes.json").read_text())
    m["source"]["language"] = "en"
    (memo / "minutes.json").write_text(json.dumps(m))

    result = vault.publish(memo, plain)

    text = result.minuta.read_text()
    assert "## Compromisos\n" in text and "plazo: sin fecha" in text and "Commitments" not in text
    assert "**Plazo:** sin fecha" in (plain / "Compromisos/2026/M1-C2.md").read_text()


@pytest.mark.parametrize("inside", ["", "MinutasVault", "data/vault"])
def test_a_vault_inside_the_public_repo_is_refused(monkeypatch, tmp_path, inside):
    project = tmp_path / "crc_memo"
    (project / inside).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(vault.config, "PROJECT_DIR", project)
    monkeypatch.setenv(vault.VAULT_ENV, str(project / inside))
    with pytest.raises(vault.VaultError, match="this repo is public"):
        vault.vault_dir()
    with pytest.raises(vault.VaultError, match="this repo is public"):
        vault.init(project / inside)


def test_init_creates_an_empty_vault_once(tmp_path):
    path = tmp_path / "MinutasVault"
    created = vault.init(path)

    assert sorted(p.relative_to(path).as_posix() for p in created) == [
        ".gitignore", ".obsidian/app.json", "Configuracion.md", "Externos.md", "Propietarios.md",
        "README.md"]
    app_json = json.loads((path / ".obsidian/app.json").read_text())
    assert app_json == {"useMarkdownLinks": True, "newLinkFormat": "relative",
                        "alwaysUpdateLinks": True}
    assert git(path, "rev-parse", "--is-inside-work-tree") == "true"
    assert "| Nombre | Lote | Teléfono | Correo | También dicen | Notas |" in \
        (path / "Propietarios.md").read_text()
    assert "| Nombre | Rol |" in (path / "Externos.md").read_text()
    assert "*.pdf" in (path / ".gitignore").read_text()

    (path / "Propietarios.md").write_text("mis propietarios")
    assert vault.init(path) == []  # nothing overwritten, git repo kept
    assert (path / "Propietarios.md").read_text() == "mis propietarios"


def test_init_in_an_existing_repo_keeps_its_history(repo):
    vault.init(repo)
    assert git(repo, "log", "--format=%s") == "init"



def test_publish_never_commits_someone_elses_work_in_progress(repo, tmp_path):
    memo = make_memo(tmp_path)
    vault.publish(memo, repo)
    note = repo / "Compromisos/2026/M1-C1.md"
    note.write_text(note.read_text() + "- 2026-10-07 · editando en Obsidian\n")
    (repo / "Diario.md").write_text("nota personal")
    m = json.loads((memo / "minutes.json").read_text())
    m["source"]["memo_date"] = "2026-09-28"
    (memo / "minutes.json").write_text(json.dumps(m))

    vault.publish(memo, repo)  # moves the minuta: a real commit

    uncommitted = [line.split()[-1] for line in git(repo, "status", "--porcelain").splitlines()]
    assert sorted(uncommitted) == ["Compromisos/2026/M1-C1.md", "Diario.md"]
    changed = git(repo, "show", "--no-renames", "--name-status", "--format=", "HEAD").splitlines()
    assert sorted(changed) == sorted([
        "D\tMinutas/2026/M1-2026-09-27/Minuta.md", "D\tMinutas/2026/M1-2026-09-27/MinutaBreve.md",
        "D\tMinutas/2026/M1-2026-09-27/Transcripcion.md",
        "A\tMinutas/2026/M1-2026-09-28/Minuta.md", "A\tMinutas/2026/M1-2026-09-28/MinutaBreve.md",
        "A\tMinutas/2026/M1-2026-09-28/Transcripcion.md"])



# --- names --------------------------------------------------------------------------

OWNERS = """# Propietarios

| Nombre | Lote | Teléfono | Correo | También dicen | Notas |
|---|---|---|---|---|---|
| Doña Rosa Pérez | L-14 | 8888-0000 | rosa@ejemplo.cr | Doña Rosa; doña Rosa; Rosita | tesorera \\| fundadora |
| Carlos Mora | L-14 | | | don Carlos; | |
| | L-20 | | | sin nombre | |
|  |  |  |  |  |  |
"""

OUTSIDERS = """| Rol | Nombre | También dicen |
|---|---|---|
| ingeniero | don Hansel | don Hansen |
| institución | el ICE | Elise; élice |

Texto después de la tabla | con barra.
"""


def write_names(path, owners=OWNERS, outsiders=OUTSIDERS):
    (path / "Propietarios.md").write_text(owners)
    (path / "Externos.md").write_text(outsiders)


def test_read_table(tmp_path):
    write_names(tmp_path)
    rows = vault.read_table(tmp_path / "Propietarios.md")
    assert rows[0]["nombre"] == "Doña Rosa Pérez" and rows[0]["tambien dicen"].startswith("Doña Rosa;")
    assert rows[0]["notas"] == "tesorera | fundadora"  # escaped bar
    assert len(rows) == 3  # the empty row is skipped
    assert vault.read_table(tmp_path / "Externos.md")[1] == \
        {"rol": "institución", "nombre": "el ICE", "tambien dicen": "Elise; élice"}
    assert vault.read_table(tmp_path / "missing.md") == []
    (tmp_path / "x.md").write_text("| solo encabezado |\n")
    assert vault.read_table(tmp_path / "x.md") == []


def test_name_map(tmp_path):
    write_names(tmp_path)
    names = vault.name_map(tmp_path)
    assert names["rosita"] == names["doña rosa"] == names["doña rosa pérez"] == "Doña Rosa Pérez"
    assert names["don hansen"] == "don Hansel" and names["elise"] == "el ICE"
    assert "sin nombre" not in names  # a row without a name is ignored
    (tmp_path / "nothing").mkdir()
    assert vault.name_map(tmp_path / "nothing") == {}


def test_a_variant_for_two_names_is_an_error(tmp_path):
    write_names(tmp_path, outsiders="| Nombre | También dicen |\n|---|---|\n| Rosa Mora | Rosita |\n")
    with pytest.raises(vault.VaultError, match="«Rosita» is listed for both"):
        vault.name_map(tmp_path)


def test_apply_names_never_touches_quotes():
    names = {"don hansen": "don Hansel", "hansen": "don Hansel", "don hansel": "don Hansel",
             "mauro": "don Mauro Arias", "don mauro arias": "don Mauro Arias"}
    text = ("Responsable: don Hansen · Hansen y don Mauro Arias — [07:01] «le pregunté a don "
            "Hansen y a Mauro» · Mauro dijo. DonMauroArias.md")
    new, changes = vault.apply_names(text, names)
    assert new == ("Responsable: don Hansel · don Hansel y don Mauro Arias — [07:01] «le pregunté "
                   "a don Hansen y a Mauro» · don Mauro Arias dijo. DonMauroArias.md")
    assert changes == {("don Hansen", "don Hansel"): 1, ("Hansen", "don Hansel"): 1,
                       ("Mauro", "don Mauro Arias"): 1}
    assert vault.apply_names("sin cambios", {}) == ("sin cambios", {})


def test_publish_applies_names(repo, tmp_path):
    write_names(repo)
    result = vault.publish(make_memo(tmp_path), repo)
    text = result.minuta.read_text()
    assert "Doña Rosa Pérez (tesorera)" in text and "· Doña Rosa Pérez · Cotizar" in text
    note = yaml.safe_load((repo / "Compromisos/2026/M1-C1.md").read_text().split("---\n")[1])
    assert note["responsables"] == ["Doña Rosa Pérez"]


def test_update_fixes_names_everywhere_once(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(vault.config, "MEMOS_DIR", tmp_path)
    memo = make_memo(tmp_path)
    first = vault.publish(memo, repo)
    (repo / "Diario.md").write_text("nota personal")  # someone's work in progress
    write_names(repo)

    result = vault.update(repo)

    assert result.names[("Doña Rosa", "Doña Rosa Pérez")] >= 2
    assert sorted(p.relative_to(repo).as_posix() for p in result.changed) == [
        "Compromisos/2026/M1-C1.md", "Minutas/2026/M1-2026-09-27/Minuta.md",
        "Minutas/2026/M1-2026-09-27/MinutaBreve.md"]
    assert "· Doña Rosa Pérez · Cotizar" in (first.minuta.parent / "MinutaBreve.md").read_text()
    assert (result.committed, result.pushed) == (True, True)
    assert git(repo, "log", "-1", "--format=%s") == \
        "Nombres: Don Carlos → Carlos Mora, Doña Rosa → Doña Rosa Pérez"
    assert [line.split()[-1] for line in git(repo, "status", "--porcelain").splitlines()] == \
        ["Diario.md", "Externos.md", "Propietarios.md"]
    # A name fix isn't a hand edit: publishing again still works without --force.
    assert vault.publish(memo, repo).number == 1

    again = vault.update(repo)  # nothing left to change
    assert (again.changed, again.committed) == ([], False)


def test_update_regenerates_a_missing_breve(tmp_path, monkeypatch):
    monkeypatch.setattr(vault.config, "MEMOS_DIR", tmp_path / "elsewhere")
    plain = tmp_path / "plain"
    plain.mkdir()
    result = vault.publish(make_memo(tmp_path), plain)
    (result.minuta.parent / "MinutaBreve.md").unlink()
    write_names(plain)  # this minuta's memo isn't on this machine: nothing to sync
    meta_free = vault.update(plain)
    assert sorted(p.name for p in meta_free.changed) == ["M1-C1.md", "Minuta.md", "MinutaBreve.md"]
    assert "not a git repo" in meta_free.warning


def test_update_on_a_hand_edited_minuta_keeps_it_marked_as_edited(tmp_path, monkeypatch):
    monkeypatch.setattr(vault.config, "MEMOS_DIR", tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    memo = make_memo(tmp_path)
    result = vault.publish(memo, plain)
    result.minuta.write_text(result.minuta.read_text() + "\nNota a mano.\n")
    write_names(plain)
    vault.update(plain)
    with pytest.raises(vault.VaultError, match="was edited"):
        vault.publish(memo, plain)



def test_update_skips_files_with_uncommitted_edits(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(vault.config, "MEMOS_DIR", tmp_path)
    first = vault.publish(make_memo(tmp_path), repo)
    note = repo / "Compromisos/2026/M1-C1.md"
    note.write_text(note.read_text() + "- a medio escribir\n")
    first.minuta.write_text(first.minuta.read_text() + "\nTambién a mano.\n")
    write_names(repo)

    result = vault.update(repo)

    assert sorted(p.name for p in result.skipped) == ["M1-C1.md", "Minuta.md"]
    assert result.changed == [] and not result.committed
    assert "Doña Rosa ·" in note.read_text()  # untouched until it's committed
    assert vault.uncommitted(tmp_path / "not-a-repo") == set()



def test_destinatarios_names_the_recipients(repo, tmp_path):
    (repo / "Configuracion.md").write_text("---\ndestinatarios: Vecinos del barrio\n---\n")
    result = vault.publish(make_memo(tmp_path), repo)
    text = result.minuta.read_text()
    assert "> **Piden a Vecinos del barrio:**" in text
    assert "· **Vecinos del barrio** · Enviar la lista" in text
    assert "reciben el audio" not in text
    assert vault.name_map(repo)["quienes reciben el audio"] == "Vecinos del barrio"


@pytest.mark.parametrize("settings", ["---\ndestinatarios:\n---\n", "sin frontmatter"])
def test_destinatarios_unset_keeps_the_generic_label(tmp_path, settings):
    (tmp_path / "Configuracion.md").write_text(settings)
    assert vault.name_map(tmp_path) == {}



def test_update_message_lists_each_rename_once(tmp_path, monkeypatch, repo):
    monkeypatch.setattr(vault.config, "MEMOS_DIR", tmp_path)
    vault.publish(make_memo(tmp_path), repo)
    (repo / "Configuracion.md").write_text("---\ndestinatarios: Vecinos del barrio\n---\n")
    result = vault.update(repo)
    assert ("Quienes reciben el audio", "Vecinos del barrio") in result.names
    assert ("quienes reciben el audio", "Vecinos del barrio") in result.names
    assert git(repo, "log", "-1", "--format=%s") == \
        "Nombres: Quienes reciben el audio → Vecinos del barrio"
