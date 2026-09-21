from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DATABASE_PATH = Path("data/intake.db")


def database_path() -> Path:
    return Path(os.getenv("DATABASE_PATH", str(DEFAULT_DATABASE_PATH)))
