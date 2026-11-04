"""Paths, store constants and runtime settings (model id, reference date)."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
RUNTIME_DIR = DATA_DIR / "runtime"

POLICIES_PDF = RAW_DIR / "políticas_da_loja.pdf"
POLICIES_MD = PROCESSED_DIR / "policies.md"
HANDOFFS_FILE = RUNTIME_DIR / "handoffs.jsonl"

STORE_TZ = ZoneInfo("America/Campo_Grande")

# Contact data, with the manual's inconsistencies already resolved (see README, Assumptions).
STORE_NAME = "Empório da Música"
STORE_ADDRESS = "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333"
STORE_PHONE = "(67) 3341-4444"
STORE_WHATSAPP = "(67) 3321-4500"
STORE_EMAIL = "contato@emporiodamusica.com.br"

DEFAULT_MODEL = "gemini-3.8-flash"


def load_env() -> None:
    """Load .env from the current directory or the project root (real env vars win)."""
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    load_dotenv(PROJECT_ROOT / ".env")


def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def store_now() -> datetime:
    """The agent's notion of "now", in the store's time zone.

    ``STORE_TODAY`` may be an ISO date (``2026-03-25``) or datetime (``2026-03-25T10:00``).
    A bare date keeps the current wall-clock time, so "is the store open?" still makes sense.
    """
    real_now = datetime.now(STORE_TZ)
    raw = os.getenv("STORE_TODAY", "").strip()
    if not raw:
        return real_now
    if "T" in raw or " " in raw:
        parsed = datetime.fromisoformat(raw)
        return parsed.replace(tzinfo=STORE_TZ) if parsed.tzinfo is None else parsed.astimezone(STORE_TZ)
    day = date.fromisoformat(raw)
    return datetime.combine(day, time(real_now.hour, real_now.minute), tzinfo=STORE_TZ)
