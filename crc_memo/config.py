"""Paths, model names, and settings. One place to change things."""

from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent

# Where memo keeps its own data (database + per-memo folders). Gitignored, never synced.
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "memo.db"
MEMOS_DIR = DATA_DIR / "memos"

# Where finished reports are written. Google Drive for desktop syncs this folder.
OUTPUT_DIR = Path.home() / "Google Drive" / "Memos"

# Models
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
# Short natural sentence with names/slang Whisper tends to misspell (max ~220 tokens).
# Seeded in Phase 3.5 from real transcripts; None = no hint.
WHISPER_INITIAL_PROMPT: str | None = None
LLM_MODEL = "qwen3:14b"

# Ollama's default context window is small and silently truncates input.
# Always pass this as `num_ctx` on every call.
LLM_NUM_CTX = 16384
# Extraction must be reproducible: same input + prompt + model -> same output, so
# `memo reprocess` comparisons show the effect of the change, not randomness.
LLM_TEMPERATURE = 0.0
LLM_SEED = 42
LLM_MAX_OUTPUT_TOKENS = 2048  # cap per call; at ~12 tokens/s that's under 3 minutes

# Transcript chunks sent to the LLM one at a time (~1.2k tokens of Spanish speech each).
CHUNK_SECONDS = 300

# Prompts live as .md files next to the code, loaded at runtime.
PROMPTS_DIR = Path(__file__).parent / "prompts"

# Costa Rican Spanish dictionary, generated once by scripts/import_dcaa.py.
GLOSSARY_PATH = Path(__file__).parent / "glossary" / "dcaa.json"
