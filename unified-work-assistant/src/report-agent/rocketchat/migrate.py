"""Compatibility entrypoint for the PostgreSQL report migration."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from migrate_to_postgres import main  # noqa: E402


if __name__ == "__main__":
    main()
