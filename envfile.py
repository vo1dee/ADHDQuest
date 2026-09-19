"""Tiny .env loader (no python-dotenv dependency). Real environment variables win."""

import os
from pathlib import Path


def load_dotenv(path: Path = Path(__file__).with_name(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))
