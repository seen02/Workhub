"""Initialize PostgreSQL and import a legacy SQLite report database once."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, func, select, text

ROOT = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("SQLITE_SOURCE_PATH", ROOT / "work_assistant.db")).resolve()
TABLES = (
    "employees", "projects", "tasks", "reports", "report_revisions",
    "chat_drafts", "chat_draft_items", "chat_draft_revisions", "chat_publications",
)
SERIAL_TABLES = (
    "employees", "projects", "tasks", "reports", "report_revisions", "chat_draft_revisions",
)


def verified_backup() -> Path | None:
    if not SOURCE.is_file():
        return None
    backup_dir = Path(os.environ.get("MIGRATION_BACKUP_PATH", ROOT / "backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"before-postgresql-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    with sqlite3.connect(f"file:{SOURCE.as_posix()}?mode=ro", uri=True) as source, sqlite3.connect(target) as backup:
        source.backup(backup)
    with sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True) as backup:
        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite backup integrity check failed")
    return target


def migrate_rows(database_url: str) -> tuple[dict[str, int], bool]:
    if not SOURCE.is_file():
        return {}, False
    source_engine = create_engine(f"sqlite:///{SOURCE.as_posix()}")
    target_engine = create_engine(database_url, pool_pre_ping=True)
    source_metadata = MetaData()
    target_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    target_metadata.reflect(bind=target_engine)
    available = [name for name in TABLES if name in source_metadata.tables]
    with target_engine.begin() as target:
        existing = sum(
            target.scalar(select(func.count()).select_from(target_metadata.tables[name])) or 0
            for name in available
        )
        if existing:
            return {
                name: target.scalar(select(func.count()).select_from(target_metadata.tables[name])) or 0
                for name in available
            }, False
        with source_engine.connect() as source:
            for name in available:
                rows = [dict(row) for row in source.execute(select(source_metadata.tables[name])).mappings()]
                if rows:
                    target.execute(target_metadata.tables[name].insert(), rows)
            for name in SERIAL_TABLES:
                if name in available:
                    target.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {name}), 1), "
                        f"(SELECT COUNT(*) > 0 FROM {name}))"
                    ))
            counts = {
                name: target.scalar(select(func.count()).select_from(target_metadata.tables[name])) or 0
                for name in available
            }
            source_counts = {
                name: source.scalar(select(func.count()).select_from(source_metadata.tables[name])) or 0
                for name in available
            }
            if counts != source_counts:
                raise RuntimeError(f"PostgreSQL row verification failed: {counts} != {source_counts}")
    return counts, True


def target_has_rows(database_url: str) -> bool:
    engine = create_engine(database_url, pool_pre_ping=True)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    available = [name for name in TABLES if name in metadata.tables]
    with engine.connect() as connection:
        return any(
            (connection.scalar(select(func.count()).select_from(metadata.tables[name])) or 0) > 0
            for name in available
        )


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
    backup = verified_backup() if SOURCE.is_file() and not target_has_rows(database_url) else None
    counts, imported = migrate_rows(database_url)
    print({
        "database": "postgresql",
        "sqlite_imported": imported,
        "rows": counts,
        "verified_backup": str(backup) if backup else None,
    })


if __name__ == "__main__":
    main()
