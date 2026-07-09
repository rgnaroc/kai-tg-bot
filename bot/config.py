"""Конфигурация Kai TG Bot."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Пути ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
DATA_DIR = PROJECT_ROOT / "data"

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
raw = os.getenv("TELEGRAM_ADMIN_IDS", "")
TELEGRAM_ADMIN_IDS = [int(x) for x in raw.split(",") if x.strip()]

# --- LLM Services ---
SERVICES_DB_PATH = DATA_DIR / "services.db"

# --- Память ---
MEMORY_DB_PATH = DATA_DIR / "memory.db"
MAX_HISTORY_MESSAGES = 50

# --- Self-Coding ---
GIT_REPO_PATH = PROJECT_ROOT
GIT_REMOTE = "origin"
GIT_BRANCH = "main"
SELF_CODE_REVIEW_CRON = "0 3 * * *"
