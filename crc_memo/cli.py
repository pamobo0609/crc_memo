"""Command-line entry point."""

import shutil
import time
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from crc_memo import config, ingest, output, pdf, summarize, transcribe, vault, views
from crc_memo.schemas import Prose

app = typer.Typer(
    help="Transcribe and summarize voice memos, locally.",
    no_args_is_help=True,
)
console = Console()


class Step(str, Enum):
    """Summarization steps, in order; `reprocess --from` reruns one and everything after it."""
    extract = "extract"
    merge = "merge"
    write = "write"
    render = "render"


STEP_FILES = {
    Step.extract: [summarize.EXTRACTIONS_NAME],
    Step.merge: [summarize.MINUTES_NAME],
    Step.write: [summarize.PROSE_NAME],
    Step.render: [output.MINUTA_NAME, output.BREVE_NAME, pdf.PDF_NAME],
}
HISTORY_DIR = "history"


def _check_date(value: str | None) -> str | None:
    if value is not None:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise typer.BadParameter("use YYYY-MM-DD, e.g. 2026-10-05") from None
    return value


SENDER = typer.Option(None, "--sender", help="Who recorded the audio (shown in the minuta).")
DATE = typer.Option(None, "--date", callback=_check_date,
                    help="Date of the audio, YYYY-MM-DD. Default: from a WhatsApp file name.")


def _set_details(folder: Path, sender: str | None, date_: str | None) -> None:
    """Save --sender / --date in meta.json."""
    values = {key: value for key, value in [("sender", sender), ("date", date_)] if value}
    if values:
        ingest.update_meta(folder, **values)


def _summarize(folder: Path) -> None:
    """Each step skips work already done, so this resumes wherever a memo stopped.
    Sender/date only affect the header, so they're refreshed without any LLM call."""
    summarize.refresh_source(folder)
    _extract_step(folder)
    _merge_step(folder)
    _write_step(folder)


def _archive_and_clear(folder: Path, first: Step) -> Path | None:
    """Copy every current output to history/<time>/ (for before/after comparisons), then
    delete the outputs of `first` and the steps after it so they run again."""
    outputs = [folder / name for names in STEP_FILES.values() for name in names
               if (folder / name).exists()]
    if not outputs:
        return None
    archive = folder / HISTORY_DIR / datetime.now().strftime("%Y-%m-%d %H.%M.%S")
    archive.mkdir(parents=True, exist_ok=True)
    for path in [*outputs, folder / ingest.META_NAME]:
        shutil.copy2(path, archive / path.name)
    steps = list(Step)
    for step in steps[steps.index(first):]:
        for name in STEP_FILES[step]:
            (folder / name).unlink(missing_ok=True)
    return archive


@app.command()
def process(
    path: Optional[Path] = typer.Argument(
        None,
        help="Audio file. Omit to open the macOS file picker.",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    lang: Optional[str] = typer.Option(
        None,
        "--lang",
        help="Language code (es, en, ...). Default: auto-detect from the first 30 seconds.",
    ),
    sender: Optional[str] = SENDER,
    date_: Optional[str] = DATE,
) -> None:
    """Transcribe and summarize an audio file."""
    if path is None:
        path = ingest.pick_file()
        if path is None:
            console.print("No file chosen.")
            raise typer.Exit(1)

    try:
        result = ingest.ingest(path, config.MEMOS_DIR)
        status = "Already ingested" if result.skipped else "[green]Ingested[/green]"
        console.print(f"{status} [bold]{result.memo_id}[/bold] → {result.folder}")
        _set_details(result.folder, sender, date_)
        _transcribe_step(result.folder, lang)
        _summarize(result.folder)
    except (ingest.IngestError, transcribe.TranscribeError, summarize.SummarizeError,
            pdf.PdfError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


def _transcribe_step(folder: Path, lang: str | None) -> None:
    """Each step skips work already done, so re-running a memo picks up where it left off."""
    if transcribe.is_transcribed(folder):
        console.print("Already transcribed")
        return

    wav = folder / ingest.WAV_NAME
    audio_seconds = transcribe.audio_duration(wav)
    length = transcribe.format_timestamp(audio_seconds)
    console.print(
        f"Transcribing {length} of audio with [bold]{config.WHISPER_MODEL}[/bold]…\n"
        "[dim](the first run downloads the model, ~1.6 GB)[/dim]"
    )
    started = time.monotonic()
    result = transcribe.transcribe(wav, config.WHISPER_MODEL, lang, config.WHISPER_INITIAL_PROMPT)
    seconds = time.monotonic() - started
    speed = audio_seconds / max(seconds, 0.001)
    loops = transcribe.find_loops(result.segments)
    transcribe.save(result, folder, {
        "model": config.WHISPER_MODEL,
        "audio_seconds": round(audio_seconds, 1),
        "seconds": round(seconds, 1),
        "speed": round(speed, 1),
        "warnings": [asdict(w) for w in loops],
    })

    console.print(
        f"[green]Transcribed[/green] {length} of audio in "
        f"{transcribe.format_timestamp(seconds)} ({speed:.1f}× real time) · "
        f"language [bold]{result.language}[/bold] · {len(result.segments)} segments → "
        f"{folder / transcribe.TRANSCRIPT_NAME}"
    )
    for w in loops:
        count = f" (×{w.count})" if w.count > 1 else ""
        console.print(
            f"[yellow]⚠ possible Whisper loop at [{transcribe.format_timestamp(w.at)}]"
            f"{count}:[/yellow] «{escape(w.text)}»"
        )
    if loops:
        console.print("[dim]Check those spots; if loops are common we'll tune Whisper.[/dim]")


def _llm_stats(stats: summarize.LLMStats) -> None:
    """One line on where a step's LLM time went (reading the prompt vs writing the answer)."""
    if not stats.calls:
        return
    fmt = transcribe.format_timestamp
    console.print(
        f"[dim]  {stats.calls} LLM calls · read {stats.prompt_tokens:,} tokens in "
        f"{fmt(stats.prompt_seconds)} · wrote {stats.output_tokens:,} tokens in "
        f"{fmt(stats.output_seconds)} ({stats.output_speed:.1f} tokens/s)"
        + (f" · model load {fmt(stats.load_seconds)}" if stats.load_seconds >= 1 else "")
        + "[/dim]"
    )
    if stats.truncated:
        console.print(f"[yellow]⚠ {stats.truncated} replies hit the output limit "
                      f"(LLM_MAX_OUTPUT_TOKENS={config.LLM_MAX_OUTPUT_TOKENS})[/yellow]")


def _extract_step(folder: Path) -> None:
    if summarize.is_extracted(folder):
        console.print("Already extracted")
        return

    started = time.monotonic()
    stats = summarize.LLMStats()
    with Progress(
        TextColumn(f"Extracting meeting notes with [bold]{config.LLM_MODEL}[/bold]"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("extract", total=None)
        results = summarize.extract(
            folder, lambda done, total: progress.update(task, completed=done, total=total), stats
        )
    elapsed = transcribe.format_timestamp(time.monotonic() - started)
    count = lambda field: sum(len(getattr(r, field)) for r in results)
    console.print(
        f"[green]Extracted[/green] {len(results)} chunks in {elapsed} · "
        f"{count('agreements')} agreements · {count('commitments')} commitments · "
        f"{count('pending')} pending (before merging) → "
        f"{folder / summarize.EXTRACTIONS_NAME}"
    )
    _llm_stats(stats)


def _merge_step(folder: Path) -> None:
    if summarize.is_merged(folder):
        console.print("Already merged")
        return

    started = time.monotonic()
    stats = summarize.LLMStats()
    with console.status("Merging chunks and removing duplicates…"):
        minutes, removed = summarize.merge(folder, stats)
    elapsed = transcribe.format_timestamp(time.monotonic() - started)
    console.print(
        f"[green]Merged[/green] in {elapsed} · removed {removed} duplicates → "
        f"{len(minutes.topics)} topics · {len(minutes.agreements)} agreements · "
        f"{len(minutes.commitments)} commitments · {len(minutes.pending)} pending → "
        f"{folder / summarize.MINUTES_NAME}"
    )
    _llm_stats(stats)


def _write_step(folder: Path) -> None:
    """The prose costs LLM calls, so it's reused; rendering is instant, so it always reruns."""
    if summarize.is_written(folder):
        console.print("Prose already written")
    else:
        started = time.monotonic()
        stats = summarize.LLMStats()
        with Progress(
            TextColumn(f"Writing the minuta with [bold]{config.LLM_MODEL}[/bold]"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("write", total=None)
            summarize.write(
                folder, lambda done, total: progress.update(task, completed=done, total=total),
                stats,
            )
        elapsed = transcribe.format_timestamp(time.monotonic() - started)
        console.print(f"[green]Wrote[/green] the prose in {elapsed} → "
                      f"{folder / summarize.PROSE_NAME}")
        _llm_stats(stats)

    for path in [*output.write(folder), pdf.write(folder / output.MINUTA_NAME)]:
        console.print(f"[green]Minuta[/green] → {path}")
    prose = Prose.model_validate_json((folder / summarize.PROSE_NAME).read_text())
    if prose.meeting_recap is False:
        console.print("[yellow]⚠ This audio doesn't seem to retell a meeting: no meeting "
                      "details in the minuta. Review it before sharing.[/yellow]")


@app.command()
def publish(
    memo_id: str = typer.Argument(..., metavar="ID", help="Memo ID (or a unique start of it)."),
    force: bool = typer.Option(False, "--force", help="Replace a minuta edited in the vault."),
    push: bool = typer.Option(True, "--push/--no-push", help="Push the vault after committing."),
) -> None:
    """Publish a memo's minuta to the vault and push.

    Numbers it (M12) and writes the minuta, its short version and PDF, the transcript and one
    note per commitment into $CRC_MEMO_VAULT, then commits and pushes.
    """
    try:
        folder = ingest.find_memo(config.MEMOS_DIR, memo_id)
        if not summarize.is_written(folder):
            raise ingest.IngestError(f"{folder.name} has no minuta yet. Run: memo process")
        result = vault.publish(folder, vault.vault_dir(), force=force, push=push)
    except (ingest.IngestError, vault.VaultError, pdf.PdfError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]Published[/green] [bold]M{result.number}[/bold] → {result.minuta}")
    console.print(f"  PDF for the group → {result.pdf}")
    if result.created:
        console.print(f"  {len(result.created)} new commitment notes in "
                      f"{vault.COMPROMISOS_DIR}/")
    _report_git(result)


def _report_git(result: vault.PublishResult | vault.UpdateResult) -> None:
    if result.warning:
        console.print(f"[yellow]⚠ {result.warning}[/yellow]")
    elif result.committed:
        console.print("  committed and pushed" if result.pushed else "  committed (not pushed)")
    else:
        console.print("  nothing changed")


vault_app = typer.Typer(help="The vault: a private git repo of minutas (Spanish markdown).",
                        no_args_is_help=True)
app.add_typer(vault_app, name="vault")


@vault_app.command("init")
def vault_init(path: Path = typer.Argument(..., help="Folder for the new vault, e.g. "
                                                       "~/Documents/MinutasVault")) -> None:
    """Create an empty vault: folders, README, templates and a git repo."""
    path = path.expanduser()
    try:
        created = vault.init(path)
    except vault.VaultError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    for file in created:
        console.print(f"[green]Created[/green] {file}")
    console.print(
        "\nNext:\n"
        "  1. Create a [bold]private[/bold] repo on GitHub (no README), then:\n"
        f"     git -C {path} remote add origin <url> && git -C {path} add -A && "
        f"git -C {path} commit -m Inicio && git -C {path} push -u origin HEAD\n"
        f"  2. export {vault.VAULT_ENV}={path}   [dim](e.g. in ~/.zshrc)[/dim]\n"
        "  3. uv run memo publish <memo id>"
    )


@vault_app.command("update")
def vault_update(
    push: bool = typer.Option(True, "--push/--no-push", help="Push the vault after committing."),
) -> None:
    """Apply the names in Propietarios.md and Externos.md to every minuta and commitment
    (never inside «quotes»), regenerate the short minutas, commit and push."""
    try:
        result = vault.update(vault.vault_dir(), push=push)
    except (vault.VaultError, pdf.PdfError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    for (found, correct), count in sorted(result.names.items()):
        console.print(f"  {found} → [bold]{correct}[/bold] ×{count}")
    console.print(f"[green]Updated[/green] {len(result.changed)} files")
    for path in result.removed:
        console.print(f"  removed {path.name}: it's no longer in its minuta")
    for path in result.skipped:
        console.print(f"[yellow]⚠ skipped {path.name}: it has uncommitted changes. Commit them, "
                      "then run this again.[/yellow]")
    _report_git(result)


@vault_app.command("check")
def vault_check() -> None:
    """Check what people edit in the vault: minutas, commitment notes, Propietarios.md and
    Externos.md. Problems are listed as file:line; ⚠ ones are worth a look."""
    try:
        root = vault.vault_dir()
    except vault.VaultError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    result = views.check(root)
    for problem in result.problems:
        mark = "[yellow]⚠[/yellow]" if problem.warning else "[red]✗[/red]"
        console.print(f"{mark} {escape(problem.show(root))}")
    warnings = len(result.problems) - len(result.errors)
    if not result.problems:
        console.print("[green]All good[/green]")
    else:
        console.print(f"{len(result.errors)} errors, {warnings} warnings")
    if result.errors:
        raise typer.Exit(1)


@app.command()
def reprocess(
    memo_id: str = typer.Argument(..., metavar="ID", help="Memo ID (or a unique start of it)."),
    from_: Optional[Step] = typer.Option(
        None, "--from",
        help="First step to rerun. Default: extract, or render when only --sender/--date change.",
    ),
    sender: Optional[str] = SENDER,
    date_: Optional[str] = DATE,
) -> None:
    """Rerun summarization, e.g. after a prompt or model change.

    Previous outputs are kept in the memo's history/ folder.
    """
    try:
        folder = ingest.find_memo(config.MEMOS_DIR, memo_id)
        if not transcribe.is_transcribed(folder):
            raise ingest.IngestError(f"{folder.name} isn't transcribed yet. Run: memo process")
        _set_details(folder, sender, date_)
        first = from_ or (Step.render if sender or date_ else Step.extract)
        archive = _archive_and_clear(folder, first)
        if archive:
            console.print(f"Previous outputs saved → {archive}")
        console.print(f"Rerunning [bold]{folder.name}[/bold] from [bold]{first.value}[/bold]")
        _summarize(folder)
    except (ingest.IngestError, summarize.SummarizeError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
