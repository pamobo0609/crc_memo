"""Command-line entry point. Commands are stubs until their phase lands."""

import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from crc_memo import config, ingest, transcribe

app = typer.Typer(
    help="Transcribe and summarize voice memos, locally.",
    no_args_is_help=True,
)
console = Console()


def _todo(phase: str) -> None:
    console.print(f"[yellow]Not implemented yet[/yellow] (coming in {phase}).")


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
        _transcribe_step(result.folder, lang)
    except (ingest.IngestError, transcribe.TranscribeError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    _todo("Phase 3")


def _transcribe_step(folder: Path, lang: str | None) -> None:
    """Each step skips work already done, so re-running a memo picks up where it left off."""
    if transcribe.is_transcribed(folder):
        console.print("Already transcribed")
        return

    wav = folder / ingest.WAV_NAME
    length = transcribe.format_timestamp(transcribe.audio_duration(wav))
    console.print(
        f"Transcribing {length} of audio with [bold]{config.WHISPER_MODEL}[/bold]…\n"
        "[dim](the first run downloads the model, ~1.6 GB)[/dim]"
    )
    started = time.monotonic()
    result = transcribe.transcribe(wav, config.WHISPER_MODEL, lang, config.WHISPER_INITIAL_PROMPT)
    transcribe.save(result, folder)
    elapsed = transcribe.format_timestamp(time.monotonic() - started)
    console.print(
        f"[green]Transcribed[/green] in {elapsed} · language [bold]{result.language}[/bold] · "
        f"{len(result.segments)} segments → {folder / transcribe.TRANSCRIPT_NAME}"
    )


@app.command("list")
def list_memos() -> None:
    """List processed memos: date, title, duration, open action items."""
    _todo("Phase 5")


@app.command()
def search(query: str = typer.Argument(..., help="Full-text search query.")) -> None:
    """Search across all transcripts and reports."""
    _todo("Phase 5")


@app.command()
def show(
    memo_id: str = typer.Argument(..., metavar="ID", help="Memo ID."),
    exec_: bool = typer.Option(False, "--exec", help="Show the executive summary."),
    full: bool = typer.Option(False, "--full", help="Show the full report."),
    transcript: bool = typer.Option(False, "--transcript", help="Show the transcript."),
) -> None:
    """Show a processed memo."""
    _todo("Phase 5")


@app.command()
def todos() -> None:
    """List open action items across all memos."""
    _todo("Phase 5")


@app.command()
def reprocess(memo_id: str = typer.Argument(..., metavar="ID", help="Memo ID.")) -> None:
    """Rerun summarization on an existing transcript."""
    _todo("Phase 3")
