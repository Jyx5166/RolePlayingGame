from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[2]


def frontend_dir() -> Path:
    return app_root() / "frontend"


def scripts_dir() -> Path:
    return app_root() / "backend" / "resources" / "scripts"


def data_dir() -> Path:
    override = os.getenv("AI_MURDER_MYSTERY_DATA_DIR")
    if override:
        return Path(override)
    if hasattr(sys, "_MEIPASS"):
        base = Path(os.getenv("LOCALAPPDATA", Path.home()))
        return base / "AIMurderMystery"
    return app_root() / "backend" / "data"
