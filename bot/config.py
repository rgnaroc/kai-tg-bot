"""Конфигурация Kai TG Bot. Все чувствительные данные через .env."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Пути ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_IDS = list(map(int, os.getenv("TELEGRAM_ADMIN_IDS", "").split(",")))

# --- LLM Providers ---
LLM_PROVIDERS = {
    "deepseek": {
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default": "deepseek-chat",
        "description": "DeepSeek API",
    },
    "groq": {
        "base_url": os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        "api_key": os.getenv("GROQ_API_KEY", ""),
        "models": [
            "llama-3.3-70b-versatile",
            "qwen/qwen3-32b",
            "qwen/qwen3.6-27b",
        ],
        "default": "llama-3.3-70b-versatile",
        "description": "Groq (быстрый, 300+ t/s)",
    },
    "openwebui": {
        "base_url": os.getenv("OWUI_BASE_URL", "https://ai.aiinfosec.ru/api"),
        "api_key": os.getenv("OWUI_API_KEY", ""),
        "models": [],  # загружаются динамически
        "default": "deepseek-chat",
        "description": "Open WebUI на германском VPS",
    },
}

# Провайдер по умолчанию
DEFAULT_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "deepseek")
DEFAULT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "deepseek-chat")

# --- Память ---
MEMORY_DB_PATH = PROJECT_ROOT / "data" / "memory.db"
MAX_HISTORY_MESSAGES = 50  # сколько сообщений хранить в контексте

# --- Self-Coding ---
GIT_REPO_PATH = PROJECT_ROOT
GIT_REMOTE = "origin"
GIT_BRANCH = "main"
SELF_CODE_REVIEW_CRON = "0 3 * * *"  # ежедневно в 3:00
