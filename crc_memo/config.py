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
# Seeded in Phase 3.5 from real transcripts; None = no hint. Public terms only (the repo is
# public): real names go in the gitignored glossary.
# ICE = Instituto Costarricense de Electricidad: Whisper wrote "ise", "hice", "elice", "el lice"
# (and the LLM made "Elice" a person); "monofásico" came out as "mono fácil" / "mono básico".
WHISPER_INITIAL_PROMPT: str | None = "Reunión con el ICE sobre la luz: monofásico o trifásico."
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
# Whisper's segments are packed into transcript lines of about this many seconds before the
# LLM sees them. With an initial_prompt Whisper cut a 27-min memo into 967 tiny segments
# ("[16:55] este,"): a timestamp every 2 words costs tokens and makes the text choppy.
LINE_SECONDS = 10
# Shorter topics join their neighbour: a 20-second "topic" is a remark inside the one around
# it, and each topic costs one LLM call when writing the minuta.
MIN_TOPIC_SECONDS = 60
# Shorter digressions aren't listed: nobody needs to skip 4 seconds.
MIN_TANGENT_SECONDS = 15

# Prompts live as .md files next to the code, loaded at runtime.
PROMPTS_DIR = Path(__file__).parent / "prompts"

# Costa Rican Spanish dictionary, generated once by scripts/import_dcaa.py.
GLOSSARY_PATH = Path(__file__).parent / "glossary" / "dcaa.json"
