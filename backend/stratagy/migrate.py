"""Programmatic `alembic upgrade head` (so `uvicorn` start-up applies migrations)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parent.parent


def upgrade(database_url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["url"] = database_url
    if database_url.startswith("sqlite:///") and not database_url.startswith("sqlite:///:memory:"):
        Path(database_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(cfg, "head")
