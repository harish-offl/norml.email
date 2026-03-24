from datetime import datetime, timezone

from backend.app.database import TABLE_NAME, get_connection, row_to_dict


LEAD_FIELDS = ("name", "email", "niche", "industry", "phone", "company")


def list_leads() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT id, name, email, niche, industry, phone, company, sent_at, last_status, last_error
            FROM {TABLE_NAME}
            ORDER BY id
            """
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def list_campaign_leads(*, only_unsent: bool = True) -> list[dict]:
    query = (
        f"""
        SELECT name, email, niche, industry, phone, company
        FROM {TABLE_NAME}
        """
        + (" WHERE sent_at IS NULL" if only_unsent else "")
        + " ORDER BY id"
    )
    with get_connection() as connection:
        rows = connection.execute(query).fetchall()
    return [row_to_dict(row) for row in rows]


def get_lead_by_email(email: str) -> dict | None:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return None

    with get_connection() as connection:
        row = connection.execute(
            f"""
            SELECT id, name, email, niche, industry, phone, company, sent_at, last_status, last_error
            FROM {TABLE_NAME}
            WHERE lower(email) = lower(?)
            """,
            (normalized_email,),
        ).fetchone()
    return row_to_dict(row)


def create_lead(lead_data: dict) -> dict:
    normalized = _normalize_lead_payload(lead_data)
    with get_connection() as connection:
        cursor = connection.execute(
            f"""
            INSERT INTO {TABLE_NAME} (name, email, niche, industry, phone, company, last_status, last_error)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', '')
            """,
            (
                normalized["name"],
                normalized["email"],
                normalized["niche"],
                normalized["industry"],
                normalized["phone"],
                normalized["company"],
            ),
        )
        row_id = cursor.lastrowid
        row = connection.execute(
            f"""
            SELECT id, name, email, niche, industry, phone, company, sent_at, last_status, last_error
            FROM {TABLE_NAME}
            WHERE id = ?
            """,
            (row_id,),
        ).fetchone()
    return row_to_dict(row) or {}


def bulk_store_leads(rows: list[dict], *, replace_existing: bool) -> tuple[int, int]:
    created = 0
    updated = 0

    with get_connection() as connection:
        if replace_existing:
            connection.execute(f"DELETE FROM {TABLE_NAME}")

        for raw_row in rows:
            row = _normalize_lead_payload(raw_row)
            existing = connection.execute(
                f"SELECT id, sent_at FROM {TABLE_NAME} WHERE lower(email) = lower(?)",
                (row["email"],),
            ).fetchone()

            if existing:
                if existing["sent_at"] is None:
                    connection.execute(
                        f"""
                        UPDATE {TABLE_NAME}
                        SET name = ?, niche = ?, industry = ?, phone = ?, company = ?,
                            email = ?, last_status = 'pending', last_error = ''
                        WHERE id = ?
                        """,
                        (
                            row["name"],
                            row["niche"],
                            row["industry"],
                            row["phone"],
                            row["company"],
                            row["email"],
                            existing["id"],
                        ),
                    )
                else:
                    connection.execute(
                        f"""
                        UPDATE {TABLE_NAME}
                        SET name = ?, niche = ?, industry = ?, phone = ?, company = ?, email = ?
                        WHERE id = ?
                        """,
                        (
                            row["name"],
                            row["niche"],
                            row["industry"],
                            row["phone"],
                            row["company"],
                            row["email"],
                            existing["id"],
                        ),
                    )
                updated += 1
            else:
                connection.execute(
                    f"""
                    INSERT INTO {TABLE_NAME} (name, email, niche, industry, phone, company, last_status, last_error)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', '')
                    """,
                    (
                        row["name"],
                        row["email"],
                        row["niche"],
                        row["industry"],
                        row["phone"],
                        row["company"],
                    ),
                )
                created += 1

    return created, updated


def leads_exist() -> bool:
    with get_connection() as connection:
        row = connection.execute(f"SELECT 1 FROM {TABLE_NAME} LIMIT 1").fetchone()
    return row is not None


def count_pending_leads() -> int:
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM {TABLE_NAME} WHERE sent_at IS NULL"
        ).fetchone()
    return int(row["count"] if row else 0)


def update_lead_delivery(
    email: str,
    *,
    last_status: str,
    last_error: str = "",
    sent: bool = False,
) -> None:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return

    if sent:
        sent_at = datetime.now(timezone.utc).isoformat()
        query = (
            f"""
            UPDATE {TABLE_NAME}
            SET last_status = ?, last_error = ?, sent_at = ?
            WHERE lower(email) = lower(?)
            """
        )
        params = (last_status, (last_error or "")[:2000], sent_at, normalized_email)
    else:
        query = (
            f"""
            UPDATE {TABLE_NAME}
            SET last_status = ?, last_error = ?
            WHERE lower(email) = lower(?)
            """
        )
        params = (last_status, (last_error or "")[:2000], normalized_email)

    with get_connection() as connection:
        connection.execute(query, params)


def _normalize_lead_payload(lead_data: dict) -> dict:
    normalized = {}
    for field in LEAD_FIELDS:
        value = lead_data.get(field, "") if lead_data else ""
        normalized[field] = (str(value).strip() if value is not None else "")

    normalized["email"] = normalized["email"].lower()
    return normalized
