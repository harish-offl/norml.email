from datetime import date, datetime, time, timedelta, timezone

from backend.app.database import (
    DEFAULT_FOLLOWUP_SETTINGS,
    EMAIL_EVENT_TABLE,
    FOLLOWUP_SETTINGS_TABLE,
    TABLE_NAME,
    get_connection,
    initialize_database,
    row_to_dict,
)


LEAD_FIELDS = ("name", "email", "niche", "industry", "phone", "company")
FOLLOWUP_STEP_FIELDS = (
    ("followup_1_delay_days", "followup_1_date", "followup_1"),
    ("followup_2_delay_days", "followup_2_date", "followup_2"),
    ("final_bump_delay_days", "final_bump_date", "final_bump"),
)
MAX_DELAY_DAYS = 90


initialize_database()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_date_value(value, field_name: str) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format.") from exc
    return parsed.isoformat()


def _normalize_thread_subject(subject: str) -> str:
    normalized = (subject or "").strip()
    while normalized.lower().startswith("re:"):
        normalized = normalized[3:].strip()
    return normalized


def _body_preview(body: str, limit: int = 500) -> str:
    preview = " ".join(str(body or "").split())
    return preview[:limit]


def _touch_label(touch_number: int) -> str:
    if touch_number <= 0:
        return "initial"
    if touch_number == 1:
        return "followup_1"
    if touch_number == 2:
        return "followup_2"
    return "final_bump"


def _lead_select_fields() -> str:
    return (
        "id, name, email, niche, industry, phone, company, sent_at, last_status, last_error, "
        "last_contacted_at, next_followup_at, followup_count, sequence_status, "
        "reply_received_at, opt_out_at, sequence_completed_at, thread_subject, last_message_id"
    )


def _read_followup_settings(connection) -> dict:
    row = connection.execute(
        f"""
        SELECT
            enabled,
            followup_1_delay_days,
            followup_2_delay_days,
            final_bump_delay_days,
            followup_1_date,
            followup_2_date,
            final_bump_date
        FROM {FOLLOWUP_SETTINGS_TABLE}
        WHERE id = 1
        """
    ).fetchone()

    settings = dict(DEFAULT_FOLLOWUP_SETTINGS)
    if row:
        settings.update(
            {
                "enabled": bool(row["enabled"]),
                "followup_1_delay_days": int(row["followup_1_delay_days"]),
                "followup_2_delay_days": int(row["followup_2_delay_days"]),
                "final_bump_delay_days": int(row["final_bump_delay_days"]),
                "followup_1_date": row["followup_1_date"] or None,
                "followup_2_date": row["followup_2_date"] or None,
                "final_bump_date": row["final_bump_date"] or None,
            }
        )
    return settings


def _coerce_day_delay(value, field_name: str) -> int:
    try:
        delay = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc

    if delay < 0 or delay > MAX_DELAY_DAYS:
        raise ValueError(f"{field_name} must be between 0 and {MAX_DELAY_DAYS}.")
    return delay


def _normalize_followup_settings(payload: dict, base: dict) -> dict:
    settings = {
        "enabled": bool(payload.get("enabled", base["enabled"])),
        "followup_1_delay_days": _coerce_day_delay(
            payload.get("followup_1_delay_days", base["followup_1_delay_days"]),
            "followup_1_delay_days",
        ),
        "followup_2_delay_days": _coerce_day_delay(
            payload.get("followup_2_delay_days", base["followup_2_delay_days"]),
            "followup_2_delay_days",
        ),
        "final_bump_delay_days": _coerce_day_delay(
            payload.get("final_bump_delay_days", base["final_bump_delay_days"]),
            "final_bump_delay_days",
        ),
        "followup_1_date": _normalize_date_value(
            payload.get("followup_1_date", base.get("followup_1_date")),
            "followup_1_date",
        ),
        "followup_2_date": _normalize_date_value(
            payload.get("followup_2_date", base.get("followup_2_date")),
            "followup_2_date",
        ),
        "final_bump_date": _normalize_date_value(
            payload.get("final_bump_date", base.get("final_bump_date")),
            "final_bump_date",
        ),
    }

    fixed_dates = [
        settings["followup_1_date"],
        settings["followup_2_date"],
        settings["final_bump_date"],
    ]
    previous_date = None
    for fixed in fixed_dates:
        if not fixed:
            continue
        parsed = date.fromisoformat(fixed)
        if previous_date and parsed < previous_date:
            raise ValueError("Follow-up dates must be in chronological order.")
        previous_date = parsed

    steps = get_followup_steps(settings)
    if settings["enabled"] and not steps:
        raise ValueError("Enable at least one follow-up delay or set a follow-up date before turning follow-ups on.")
    return settings


def get_followup_steps(settings: dict | None = None) -> list[dict]:
    settings = dict(DEFAULT_FOLLOWUP_SETTINGS if settings is None else settings)

    steps = []
    encountered_disabled_step = False
    for index, (delay_field, date_field, touch_type) in enumerate(FOLLOWUP_STEP_FIELDS, start=1):
        delay_days = int(settings.get(delay_field, 0) or 0)
        fixed_date = _normalize_date_value(settings.get(date_field), date_field)
        enabled_step = delay_days > 0 or bool(fixed_date)
        if not enabled_step:
            encountered_disabled_step = True
            continue
        if encountered_disabled_step:
            raise ValueError("Follow-up steps must be enabled in order without gaps (by date or delay).")
        steps.append(
            {
                "number": index,
                "touch_type": touch_type,
                "delay_days": delay_days,
                "fixed_date": fixed_date,
            }
        )

    return steps


def _next_followup_at(reference_time: str, completed_followups: int, settings: dict) -> str | None:
    if not settings.get("enabled"):
        return None

    steps = get_followup_steps(settings)
    if completed_followups >= len(steps):
        return None

    step = steps[completed_followups]
    fixed_date = step.get("fixed_date")
    if fixed_date:
        fixed_date_obj = date.fromisoformat(fixed_date)
        fixed_datetime = datetime.combine(fixed_date_obj, time(hour=9, minute=0), tzinfo=timezone.utc)
        return fixed_datetime.isoformat()

    base_time = _parse_datetime(reference_time) or _now()
    delay_days = step["delay_days"]
    return (base_time + timedelta(days=delay_days)).isoformat()


def _get_followup_queue_summary(connection, settings: dict) -> dict:
    if not settings.get("enabled"):
        return {
            "due_count": 0,
            "scheduled_count": 0,
            "active_count": 0,
            "next_due_at": None,
        }

    now_iso = _now_iso()
    max_followups = len(get_followup_steps(settings))
    rows = connection.execute(
        f"""
        SELECT followup_count, next_followup_at
        FROM {TABLE_NAME}
        WHERE sent_at IS NOT NULL
          AND next_followup_at IS NOT NULL
          AND sequence_status = 'active'
          AND reply_received_at IS NULL
          AND opt_out_at IS NULL
        """
    ).fetchall()

    due_count = 0
    scheduled_count = 0
    next_due_at = None

    for row in rows:
        if int(row["followup_count"] or 0) >= max_followups:
            continue

        next_followup_at = row["next_followup_at"]
        if not next_followup_at:
            continue

        if next_followup_at <= now_iso:
            due_count += 1
        else:
            scheduled_count += 1
            if next_due_at is None or next_followup_at < next_due_at:
                next_due_at = next_followup_at

    return {
        "due_count": due_count,
        "scheduled_count": scheduled_count,
        "active_count": due_count + scheduled_count,
        "next_due_at": next_due_at,
    }


def get_followup_settings() -> dict:
    with get_connection() as connection:
        settings = _read_followup_settings(connection)
        return {**settings, **_get_followup_queue_summary(connection, settings)}


def update_followup_settings(payload: dict) -> dict:
    with get_connection() as connection:
        current = _read_followup_settings(connection)
        settings = _normalize_followup_settings(payload or {}, current)

        connection.execute(
            f"""
            UPDATE {FOLLOWUP_SETTINGS_TABLE}
            SET enabled = ?,
                followup_1_delay_days = ?,
                followup_2_delay_days = ?,
                final_bump_delay_days = ?,
                followup_1_date = ?,
                followup_2_date = ?,
                final_bump_date = ?,
                updated_at = ?
            WHERE id = 1
            """,
            (
                int(settings["enabled"]),
                settings["followup_1_delay_days"],
                settings["followup_2_delay_days"],
                settings["final_bump_delay_days"],
                settings["followup_1_date"],
                settings["followup_2_date"],
                settings["final_bump_date"],
                _now_iso(),
            ),
        )

        if not settings["enabled"]:
            connection.execute(
                f"""
                UPDATE {TABLE_NAME}
                SET next_followup_at = NULL,
                    sequence_status = CASE
                        WHEN sent_at IS NULL THEN 'pending'
                        WHEN reply_received_at IS NOT NULL OR opt_out_at IS NOT NULL THEN 'stopped'
                        ELSE 'completed'
                    END,
                    sequence_completed_at = CASE
                        WHEN sent_at IS NULL THEN sequence_completed_at
                        WHEN reply_received_at IS NOT NULL OR opt_out_at IS NOT NULL THEN sequence_completed_at
                        ELSE COALESCE(sequence_completed_at, last_contacted_at, sent_at)
                    END
                WHERE sequence_status = 'active'
                """
            )

        return {**settings, **_get_followup_queue_summary(connection, settings)}


def list_leads() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT {_lead_select_fields()}
            FROM {TABLE_NAME}
            ORDER BY id
            """
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def list_campaign_leads(*, only_unsent: bool = True) -> list[dict]:
    if only_unsent:
        return list_pending_initial_leads()
    return list_leads()


def list_pending_initial_leads() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT {_lead_select_fields()}
            FROM {TABLE_NAME}
            WHERE sent_at IS NULL
              AND reply_received_at IS NULL
              AND opt_out_at IS NULL
              AND COALESCE(sequence_status, 'pending') != 'paused'
            ORDER BY id
            """
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def list_due_followup_leads(settings: dict | None = None) -> list[dict]:
    resolved_settings = get_followup_settings() if settings is None else settings
    if not resolved_settings.get("enabled"):
        return []

    max_followups = len(get_followup_steps(resolved_settings))
    if max_followups == 0:
        return []

    now_iso = _now_iso()
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT {_lead_select_fields()}
            FROM {TABLE_NAME}
            WHERE sent_at IS NOT NULL
              AND next_followup_at IS NOT NULL
              AND next_followup_at <= ?
              AND sequence_status = 'active'
              AND reply_received_at IS NULL
              AND opt_out_at IS NULL
            ORDER BY next_followup_at, id
            """,
            (now_iso,),
        ).fetchall()

    leads = []
    for row in rows:
        lead = row_to_dict(row) or {}
        if int(lead.get("followup_count") or 0) >= max_followups:
            continue
        leads.append(lead)
    return leads


def list_outreach_queue(settings: dict | None = None) -> list[dict]:
    resolved_settings = get_followup_settings() if settings is None else settings

    queue = []
    for lead in list_due_followup_leads(resolved_settings):
        touch_number = int(lead.get("followup_count") or 0) + 1
        lead["touch_number"] = touch_number
        lead["touch_type"] = _touch_label(touch_number)
        lead["scheduled_for"] = lead.get("next_followup_at")
        queue.append(lead)

    for lead in list_pending_initial_leads():
        lead["touch_number"] = 0
        lead["touch_type"] = "initial"
        lead["scheduled_for"] = None
        queue.append(lead)

    return queue


def get_lead_by_email(email: str) -> dict | None:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return None

    with get_connection() as connection:
        row = connection.execute(
            f"""
            SELECT {_lead_select_fields()}
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
            INSERT INTO {TABLE_NAME} (
                name,
                email,
                niche,
                industry,
                phone,
                company,
                last_status,
                last_error,
                followup_count,
                sequence_status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending', '', 0, 'pending')
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
            SELECT {_lead_select_fields()}
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
                        SET name = ?,
                            niche = ?,
                            industry = ?,
                            phone = ?,
                            company = ?,
                            email = ?,
                            last_status = 'pending',
                            last_error = '',
                            last_contacted_at = NULL,
                            next_followup_at = NULL,
                            followup_count = 0,
                            sequence_status = 'pending',
                            reply_received_at = NULL,
                            opt_out_at = NULL,
                            sequence_completed_at = NULL,
                            thread_subject = '',
                            last_message_id = ''
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
                        SET name = ?,
                            niche = ?,
                            industry = ?,
                            phone = ?,
                            company = ?,
                            email = ?
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
                    INSERT INTO {TABLE_NAME} (
                        name,
                        email,
                        niche,
                        industry,
                        phone,
                        company,
                        last_status,
                        last_error,
                        followup_count,
                        sequence_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', '', 0, 'pending')
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
            f"""
            SELECT COUNT(*) AS count
            FROM {TABLE_NAME}
            WHERE sent_at IS NULL
              AND reply_received_at IS NULL
              AND opt_out_at IS NULL
              AND COALESCE(sequence_status, 'pending') != 'paused'
            """
        ).fetchone()
    return int(row["count"] if row else 0)


def count_due_followups(settings: dict | None = None) -> int:
    return len(list_due_followup_leads(settings))


def count_ready_outreach(settings: dict | None = None) -> int:
    resolved_settings = get_followup_settings() if settings is None else settings
    due_count = count_due_followups(resolved_settings) if resolved_settings.get("enabled") else 0
    return count_pending_leads() + due_count


def get_thread_context(lead_id: int) -> dict:
    with get_connection() as connection:
        lead_row = connection.execute(
            f"""
            SELECT thread_subject, last_message_id
            FROM {TABLE_NAME}
            WHERE id = ?
            """,
            (lead_id,),
        ).fetchone()
        reference_rows = connection.execute(
            f"""
            SELECT message_id
            FROM {EMAIL_EVENT_TABLE}
            WHERE lead_id = ?
              AND status = 'sent'
              AND message_id != ''
            ORDER BY id
            """,
            (lead_id,),
        ).fetchall()

    references = [row["message_id"] for row in reference_rows if row["message_id"]]
    return {
        "thread_subject": (lead_row["thread_subject"] if lead_row else "") or "",
        "last_message_id": (lead_row["last_message_id"] if lead_row else "") or "",
        "references": references,
    }


def record_outreach_success(
    lead_id: int,
    *,
    touch_type: str,
    touch_number: int,
    subject: str,
    body: str,
    message_id: str,
    in_reply_to: str = "",
    scheduled_for: str | None = None,
    settings: dict | None = None,
) -> None:
    now_iso = _now_iso()
    resolved_settings = get_followup_settings() if settings is None else settings

    with get_connection() as connection:
        lead_row = connection.execute(
            f"""
            SELECT sent_at, thread_subject
            FROM {TABLE_NAME}
            WHERE id = ?
            """,
            (lead_id,),
        ).fetchone()
        if not lead_row:
            return

        thread_subject = (lead_row["thread_subject"] or "").strip() or _normalize_thread_subject(subject)
        next_followup_at = _next_followup_at(now_iso, touch_number, resolved_settings)
        sequence_status = "active" if next_followup_at else "completed"
        sequence_completed_at = now_iso if sequence_status == "completed" else None
        first_sent_at = lead_row["sent_at"] or now_iso

        connection.execute(
            f"""
            INSERT INTO {EMAIL_EVENT_TABLE} (
                lead_id,
                touch_number,
                touch_type,
                subject,
                body_preview,
                scheduled_for,
                sent_at,
                status,
                message_id,
                in_reply_to,
                error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'sent', ?, ?, '')
            """,
            (
                lead_id,
                touch_number,
                touch_type,
                subject,
                _body_preview(body),
                scheduled_for,
                now_iso,
                message_id,
                in_reply_to,
            ),
        )
        connection.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET sent_at = ?,
                last_status = 'sent',
                last_error = '',
                last_contacted_at = ?,
                next_followup_at = ?,
                followup_count = ?,
                sequence_status = ?,
                sequence_completed_at = ?,
                thread_subject = ?,
                last_message_id = ?
            WHERE id = ?
            """,
            (
                first_sent_at,
                now_iso,
                next_followup_at,
                max(0, touch_number),
                sequence_status,
                sequence_completed_at,
                thread_subject,
                message_id,
                lead_id,
            ),
        )


def record_outreach_failure(
    lead_id: int,
    *,
    touch_type: str,
    touch_number: int,
    subject: str,
    error_message: str,
    scheduled_for: str | None = None,
) -> None:
    error_text = (error_message or "")[:2000]

    with get_connection() as connection:
        lead_row = connection.execute(
            f"SELECT sent_at, sequence_status FROM {TABLE_NAME} WHERE id = ?",
            (lead_id,),
        ).fetchone()
        if not lead_row:
            return

        sequence_status = (
            "pending"
            if lead_row["sent_at"] is None
            else (lead_row["sequence_status"] or "active")
        )

        connection.execute(
            f"""
            INSERT INTO {EMAIL_EVENT_TABLE} (
                lead_id,
                touch_number,
                touch_type,
                subject,
                body_preview,
                scheduled_for,
                sent_at,
                status,
                message_id,
                in_reply_to,
                error
            )
            VALUES (?, ?, ?, ?, '', ?, NULL, 'failed', '', '', ?)
            """,
            (
                lead_id,
                touch_number,
                touch_type,
                subject,
                scheduled_for,
                error_text,
            ),
        )
        connection.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET last_status = 'failed',
                last_error = ?,
                sequence_status = ?
            WHERE id = ?
            """,
            (error_text, sequence_status, lead_id),
        )


def record_outreach_skip(
    lead_id: int,
    *,
    touch_type: str,
    touch_number: int,
    subject: str,
    reason: str,
    scheduled_for: str | None = None,
) -> None:
    reason_text = (reason or "")[:2000]

    with get_connection() as connection:
        lead_row = connection.execute(
            f"SELECT sent_at, sequence_status FROM {TABLE_NAME} WHERE id = ?",
            (lead_id,),
        ).fetchone()
        if not lead_row:
            return

        sequence_status = (
            "pending"
            if lead_row["sent_at"] is None
            else (lead_row["sequence_status"] or "active")
        )

        connection.execute(
            f"""
            INSERT INTO {EMAIL_EVENT_TABLE} (
                lead_id,
                touch_number,
                touch_type,
                subject,
                body_preview,
                scheduled_for,
                sent_at,
                status,
                message_id,
                in_reply_to,
                error
            )
            VALUES (?, ?, ?, ?, '', ?, NULL, 'skipped', '', '', ?)
            """,
            (
                lead_id,
                touch_number,
                touch_type,
                subject,
                scheduled_for,
                reason_text,
            ),
        )
        connection.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET last_status = 'skipped',
                last_error = ?,
                sequence_status = ?
            WHERE id = ?
            """,
            (reason_text, sequence_status, lead_id),
        )


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
        sent_at = _now_iso()
        query = (
            f"""
            UPDATE {TABLE_NAME}
            SET last_status = ?,
                last_error = ?,
                sent_at = ?,
                last_contacted_at = ?
            WHERE lower(email) = lower(?)
            """
        )
        params = (last_status, (last_error or "")[:2000], sent_at, sent_at, normalized_email)
    else:
        query = (
            f"""
            UPDATE {TABLE_NAME}
            SET last_status = ?,
                last_error = ?
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
