import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.env_utils import BASE_DIR, DATA_DIR, load_project_env


TABLE_NAME = "app_lead"
EMAIL_EVENT_TABLE = "app_lead_email_event"
FOLLOWUP_SETTINGS_TABLE = "app_followup_settings"

DEFAULT_FOLLOWUP_SETTINGS = {
    "enabled": False,
    "followup_1_delay_days": 3,
    "followup_2_delay_days": 7,
    "final_bump_delay_days": 12,
    "followup_1_date": None,
    "followup_2_date": None,
    "final_bump_date": None,
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if column_name not in _column_names(connection, table_name):
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


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

        _ensure_column(connection, TABLE_NAME, "last_contacted_at", "last_contacted_at DATETIME NULL")
        _ensure_column(connection, TABLE_NAME, "next_followup_at", "next_followup_at DATETIME NULL")
        _ensure_column(connection, TABLE_NAME, "followup_count", "followup_count INTEGER NOT NULL DEFAULT 0")
        _ensure_column(
            connection,
            TABLE_NAME,
            "sequence_status",
            "sequence_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
        )





        _ensure_column(connection, TABLE_NAME, "reply_received_at", "reply_received_at DATETIME NULL")
        _ensure_column(connection, TABLE_NAME, "opt_out_at", "opt_out_at DATETIME NULL")
        _ensure_column(connection, TABLE_NAME, "sequence_completed_at", "sequence_completed_at DATETIME NULL")
        _ensure_column(connection, TABLE_NAME, "thread_subject", "thread_subject TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, TABLE_NAME, "last_message_id", "last_message_id TEXT NOT NULL DEFAULT ''")

        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {EMAIL_EVENT_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                touch_number INTEGER NOT NULL DEFAULT 0,
                touch_type VARCHAR(20) NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                body_preview TEXT NOT NULL DEFAULT '',
                scheduled_for DATETIME NULL,
                sent_at DATETIME NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                message_id TEXT NOT NULL DEFAULT '',
                in_reply_to TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lead_id) REFERENCES {TABLE_NAME}(id) ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {FOLLOWUP_SETTINGS_TABLE} (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER NOT NULL DEFAULT 0,
                followup_1_delay_days INTEGER NOT NULL DEFAULT 3,
                followup_2_delay_days INTEGER NOT NULL DEFAULT 7,
                final_bump_delay_days INTEGER NOT NULL DEFAULT 12,
                followup_1_date TEXT NULL,
                followup_2_date TEXT NULL,
                final_bump_date TEXT NULL,
                updated_at DATETIME NULL
            )
            """
        )
        _ensure_column(connection, FOLLOWUP_SETTINGS_TABLE, "followup_1_date", "followup_1_date TEXT NULL")
        _ensure_column(connection, FOLLOWUP_SETTINGS_TABLE, "followup_2_date", "followup_2_date TEXT NULL")
        _ensure_column(connection, FOLLOWUP_SETTINGS_TABLE, "final_bump_date", "final_bump_date TEXT NULL")
        connection.execute(
            f"""
            INSERT INTO {FOLLOWUP_SETTINGS_TABLE} (
                id,
                enabled,
                followup_1_delay_days,
                followup_2_delay_days,
                final_bump_delay_days,
                followup_1_date,
                followup_2_date,
                final_bump_date,
                updated_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                int(DEFAULT_FOLLOWUP_SETTINGS["enabled"]),
                DEFAULT_FOLLOWUP_SETTINGS["followup_1_delay_days"],
                DEFAULT_FOLLOWUP_SETTINGS["followup_2_delay_days"],
                DEFAULT_FOLLOWUP_SETTINGS["final_bump_delay_days"],
                DEFAULT_FOLLOWUP_SETTINGS["followup_1_date"],
                DEFAULT_FOLLOWUP_SETTINGS["followup_2_date"],
                DEFAULT_FOLLOWUP_SETTINGS["final_bump_date"],
                _utcnow_iso(),
            ),
        )

        connection.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET last_contacted_at = sent_at
            WHERE sent_at IS NOT NULL
              AND last_contacted_at IS NULL
            """
        )
        connection.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET sequence_status = CASE
                WHEN opt_out_at IS NOT NULL OR reply_received_at IS NOT NULL THEN 'stopped'
                WHEN sent_at IS NULL THEN 'pending'
                WHEN next_followup_at IS NOT NULL THEN 'active'
                ELSE 'completed'
            END
            WHERE sequence_status IS NULL
               OR trim(sequence_status) = ''
               OR (sequence_status = 'pending' AND sent_at IS NOT NULL)
            """
        )
        connection.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET sequence_completed_at = COALESCE(sequence_completed_at, sent_at)
            WHERE sent_at IS NOT NULL
              AND next_followup_at IS NULL
              AND sequence_status = 'completed'
            """
        )

        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_sent_at ON {TABLE_NAME}(sent_at)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_email_lower ON {TABLE_NAME}(email)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_next_followup_at ON {TABLE_NAME}(next_followup_at)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_sequence_status ON {TABLE_NAME}(sequence_status)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{EMAIL_EVENT_TABLE}_lead_id ON {EMAIL_EVENT_TABLE}(lead_id)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{EMAIL_EVENT_TABLE}_status ON {EMAIL_EVENT_TABLE}(status)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{EMAIL_EVENT_TABLE}_sent_at ON {EMAIL_EVENT_TABLE}(sent_at)"
        )
