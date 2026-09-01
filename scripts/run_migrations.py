#!/usr/bin/env python
"""Thin wrapper: `alembic upgrade head`, run from the repo root regardless of cwd.

Usage: python scripts/run_migrations.py
"""

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"


def main() -> int:
    return subprocess.call(["alembic", "upgrade", "head"], cwd=BACKEND_DIR)


if __name__ == "__main__":
    sys.exit(main())
