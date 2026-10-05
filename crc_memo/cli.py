"""Command-line entry point. Commands are stubs until their phase lands."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from crc_memo import config, ingest

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
) -> None:
    """Transcribe and summarize an audio file."""
    if path is None:
        path = ingest.pick_file()
        if path is None:
            console.print("No file chosen.")
            raise typer.Exit(1)

    try:
        result = ingest.ingest(path, config.MEMOS_DIR)
    except ingest.IngestError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    status = "Already processed" if result.skipped else "[green]Ingested[/green]"
    console.print(f"{status} [bold]{result.memo_id}[/bold] → {result.folder}")
    _todo("Phase 2")


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
