"""Central settings, read from environment / .env."""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Online brain: Claude -------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Check https://docs.claude.com/en/docs/about-claude/models for current model IDs.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1024"))

# --- Offline brain: a local model through Ollama (optional) ---------------
USE_OLLAMA = os.getenv("USE_OLLAMA", "true").lower() == "true"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")  # must support tool calling

# --- Storage --------------------------------------------------------------
# SQLite keeps everything on your laptop (works offline). PostgreSQL also works:
# postgresql+psycopg://pa:pa@localhost:5432/pa
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pa.db")

# --- Personal -------------------------------------------------------------
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Ava")
USER_NAME = os.getenv("USER_NAME", "Betty")
TIMEZONE = os.getenv("TIMEZONE", "Africa/Nairobi")

# --- Behaviour ------------------------------------------------------------
ONBOARDING_DAYS = int(os.getenv("ONBOARDING_DAYS", "10"))
AFFIRMATION_HOUR = int(os.getenv("AFFIRMATION_HOUR", "6"))   # local hour for the morning refresh
AFFIRMATION_BANK_DAYS = int(os.getenv("AFFIRMATION_BANK_DAYS", "7"))  # days kept ready for offline
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "20"))
