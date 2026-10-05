# Contributing to crc_memo

These rules apply to everyone working in this repo — people and AI assistants alike.
Project context (what crc_memo is, its stack and roadmap) lives in [CLAUDE.md](CLAUDE.md).

## Rules

1. **Zero cost, unless hard blocked.** Applies to everything: runtime, models, dev tools,
   CI, hosting, services. Always look for the free/open-source route first.
   - A **hard block** is when no free option can do the job — not when the free option is
     slower or less convenient.
   - When hard blocked, **stop and flag it**; don't assume either way (don't assume paying
     is fine, and don't assume something is blocked without checking the free options):
     ```
     🚫 HARD BLOCK (cost): <what is blocked>
     Free options tried: <what and why each fails>
     Cost: <what it would cost>
     Options: <pay / change scope / defer>
     ```
     Then wait for the maintainer's decision.
2. **Real memo data never leaves the machine** — not in git, CI, issues, or test fixtures.
   `data/` is gitignored. Tests use generated audio and made-up text only.
3. **Every change ships with tests.** 100% line + branch coverage is enforced by
   `pyproject.toml`. Don't lower the gate or add `# pragma: no cover` without the
   maintainer's OK.
4. **Tests are fast and offline.** Never touch the real `data/`, the network, Ollama or
   Whisper models — fake them with `monkeypatch`. Real `ffmpeg` is fine (local, fast,
   installed in CI).
   - **Exception: opt-in integration tests** (`@pytest.mark.integration`, in
     `tests/integration/`) may run real models on synthetic input to guard output quality.
     They never run by default: `uv run pytest -m integration --no-cov`.
5. **CI must stay green.** GitHub Actions (`.github/workflows/tests.yml`, `ubuntu-latest`)
   runs the suite on every push to `main` and on PRs. It's free for public repos and only
   sees code + synthetic test audio, so it doesn't break the local-only rule.
   The app targets macOS, but the code must import and test on Linux: keep macOS-only
   pieces (`osascript`, `mlx-whisper`) behind functions tests can fake, and give
   macOS-only deps a platform marker (`; sys_platform == 'darwin'`).
6. **The repo is public** — nothing personal in commits (e.g. `data/glossary.toml` with real
   names stays gitignored).
7. **Check current versions** (libraries, GitHub Actions, models) instead of relying on memory.

## Running the tests

```sh
brew install ffmpeg uv     # macOS; on Linux: apt install ffmpeg, then install uv
uv sync
uv run pytest              # fails if coverage drops below 100%
```
