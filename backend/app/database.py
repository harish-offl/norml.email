import os
import sqlite3
from pathlib import Path

from backend.env_utils import BASE_DIR, DATA_DIR, load_project_env


TABLE_NAME = "app_lead"


def _resolve_db_path() -> Path:
    load_project_env()
    raw_db_name = os.getenv("DATABASE_URL", str(DATA_DIR / "leads.db"))
    if raw_db_name.startswith("sqlite:///"):
        raw_db_name = raw_db_name.replace("sqlite:///", "", 1)
    elif raw_db_name.startswith("sqlite://"):
        raw_db_name = raw_db_name.replace("sqlite://", "", 1)

    db_path = Path(raw_db_name)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    return db_path


DB_PATH = _resolve_db_path()


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NULL,
                email VARCHAR(254) NOT NULL UNIQUE,
                niche VARCHAR(100) NULL,
                industry VARCHAR(100) NULL,
                phone VARCHAR(20) NULL,
                company VARCHAR(100) NULL,
                last_error TEXT NOT NULL DEFAULT '',
                last_status VARCHAR(20) NOT NULL DEFAULT 'pending',
                sent_at DATETIME NULL
            )
            """
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_sent_at ON {TABLE_NAME}(sent_at)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_email_lower ON {TABLE_NAME}(email)"
        )
