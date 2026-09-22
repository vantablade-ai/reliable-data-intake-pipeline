from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DATABASE_PATH = Path("data/intake.db")
DEFAULT_MAX_BATCH_SIZE = 100


def database_path() -> Path:
    return Path(os.getenv("DATABASE_PATH", str(DEFAULT_DATABASE_PATH)))


def max_batch_size() -> int:
    value = int(os.getenv("MAX_BATCH_SIZE", str(DEFAULT_MAX_BATCH_SIZE)))
    if value < 1:
        raise ValueError("MAX_BATCH_SIZE must be positive")
    return value
