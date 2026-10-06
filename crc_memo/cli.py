"""Command-line entry point. Commands are stubs until their phase lands."""

import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from crc_memo import config, ingest, output, summarize, transcribe

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
        _extract_step(result.folder)
        _merge_step(result.folder)
        _write_step(result.folder)
    except (ingest.IngestError, transcribe.TranscribeError, summarize.SummarizeError) as e:
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

    for path in output.write(folder):
        console.print(f"[green]Minuta[/green] → {path}")


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
