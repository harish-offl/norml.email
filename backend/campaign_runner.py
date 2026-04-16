import concurrent.futures
import csv
import os
import secrets
import threading
import time

from backend.ai_engine import assess_email_quality, generate_cold_email, generate_followup_email
from backend.app.campaign_status import finish_campaign, record_campaign_progress
from backend.app.crud import (
    get_followup_settings,
    get_sender_profile,
    get_thread_context,
    list_outreach_queue,
    record_outreach_failure,
    record_outreach_skip,
    record_outreach_success,
)
from backend.config import DELAY_BETWEEN_EMAILS, MAX_CONCURRENT_EMAILS
from backend.email_quality import (
    is_valid_email_format,
    is_disposable_email,
    should_skip_email,
    classify_bounce,
)
from backend.env_utils import BASE_DIR, DATA_DIR
from backend.smtp_sender import SMTPSender

_SENDER_NAME = os.getenv("SENDER_NAME", "Ram Viswanth")
_AGENCY_NAME = os.getenv("AGENCY_NAME", "Arrise Digital")

_lead_update_lock = threading.Lock()


def _parse_email_content(email_content):
    lines = email_content.split("\n")
    if not lines:
        return "Growth opportunity", "Hi there,\n\nI'd like to discuss growth opportunities."
    subject = lines[0].replace("Subject: ", "").strip() or "Growth opportunity"
    body = "\n".join(lines[1:]).strip()
    if not body:
        body = "Hi there,\n\nI'd like to discuss growth opportunities."
    return subject, body


def _deduplicate_outreach(queue):
    deduplicated = []
    seen = set()

    for row in queue:
        email = (row.get("email") or "").strip().lower()
        touch_type = (row.get("touch_type") or "initial").strip().lower()
        key = (email, touch_type)
        if not email or key in seen:
            continue

        normalized = dict(row)
        normalized["email"] = email
        deduplicated.append(normalized)
        seen.add(key)

    return deduplicated


def _load_outreach_queue(use_csv_fallback=True):
    settings = get_followup_settings()
    queue = list_outreach_queue(settings)
    if queue:
        return _deduplicate_outreach(queue), settings

    if not use_csv_fallback:
        print("No pending leads or due follow-ups found in database")
        return [], settings

    fallback_queue = []
    try:
        csv_path = DATA_DIR / "leads.csv"
        if not csv_path.exists():
            csv_path = BASE_DIR / "leads.csv"
        with open(csv_path, encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                fallback_queue.append(
                    {
                        **row,
                        "id": None,
                        "touch_number": 0,
                        "touch_type": "initial",
                        "scheduled_for": None,
                    }
                )
    except FileNotFoundError:
        print("No leads.csv file found and no outreach queue in database")
        return [], settings

    return _deduplicate_outreach(fallback_queue), settings


def _split_chunks(items, chunk_count):
    chunk_count = max(1, min(chunk_count, len(items)))
    chunks = [[] for _ in range(chunk_count)]
    for idx, item in enumerate(items):
        chunks[idx % chunk_count].append(item)
    return [chunk for chunk in chunks if chunk]


def _sender_name(profile):
    return (profile.get("sender_name") or _SENDER_NAME).strip()


def _agency_name(profile):
    return (profile.get("agency_name") or _AGENCY_NAME).strip()


def _tracking_pixel_url(profile, tracking_token):
    base_url = str(profile.get("tracking_base_url") or "").strip().rstrip("/")
    if not tracking_token or not base_url or not profile.get("open_tracking_enabled"):
        return ""
    return f"{base_url}/t/{tracking_token}.gif"


def _message_for_row(row, sender_profile):
    touch_number = int(row.get("touch_number") or 0)
    if touch_number <= 0:
        return generate_cold_email(row, sender_profile=sender_profile)

    thread_subject = (row.get("thread_subject") or "").strip()
    return generate_followup_email(row, touch_number, thread_subject=thread_subject, sender_profile=sender_profile)


def _record_success(
    row,
    *,
    subject,
    body,
    message_id,
    in_reply_to,
    tracking_token,
    copy_quality_score,
    copy_quality_flags,
    settings,
):
    lead_id = row.get("id")
    if lead_id is None:
        return

    with _lead_update_lock:
        record_outreach_success(
            int(lead_id),
            touch_type=row.get("touch_type") or "initial",
            touch_number=int(row.get("touch_number") or 0),
            subject=subject,
            body=body,
            message_id=message_id,
            in_reply_to=in_reply_to,
            tracking_token=tracking_token,
            copy_quality_score=copy_quality_score,
            copy_quality_flags=copy_quality_flags,
            scheduled_for=row.get("scheduled_for"),
            settings=settings,
        )


def _record_failure(row, *, subject, error_message):
    lead_id = row.get("id")
    if lead_id is None:
        return

    with _lead_update_lock:
        record_outreach_failure(
            int(lead_id),
            touch_type=row.get("touch_type") or "initial",
            touch_number=int(row.get("touch_number") or 0),
            subject=subject,
            error_message=error_message,
            scheduled_for=row.get("scheduled_for"),
        )


def _record_skip(row, *, subject, reason):
    lead_id = row.get("id")
    if lead_id is None:
        return

    with _lead_update_lock:
        record_outreach_skip(
            int(lead_id),
            touch_type=row.get("touch_type") or "initial",
            touch_number=int(row.get("touch_number") or 0),
            subject=subject,
            reason=reason,
            scheduled_for=row.get("scheduled_for"),
        )


def _process_chunk(worker_id, rows, settings, sender_profile):
    sent = 0
    skipped = 0
    failed = 0
    gen_seconds = 0.0
    send_seconds = 0.0

    with SMTPSender() as sender:
        for row in rows:
            email = (row.get("email") or "").strip().lower()
            solution = (row.get("niche") or "").strip()
            touch_type = row.get("touch_type") or "initial"
            touch_number = int(row.get("touch_number") or 0)
            default_subject = (
                (row.get("thread_subject") or "").strip()
                or f"{solution or 'Growth'} growth strategy for {(row.get('company') or 'your business').strip()}"
            )

            # ✓ Validate email format and skip problematic addresses
            skip_email, skip_reason = should_skip_email(email)
            if not solution:
                skipped += 1
                _record_skip(row, subject=default_subject, reason="Missing solution/niche")
                record_campaign_progress(skipped=1)
                print(f"[worker-{worker_id}] Skipped {email or 'unknown'}: missing solution/niche")
                continue
            
            if skip_email:
                skipped += 1
                _record_skip(row, subject=default_subject, reason=skip_reason)
                record_campaign_progress(skipped=1)
                print(f"[worker-{worker_id}] Skipped {email}: {skip_reason}")
                continue

            thread_context = {"last_message_id": "", "references": []}
            if touch_number > 0 and row.get("id") is not None:
                thread_context = get_thread_context(int(row["id"]))
                if thread_context.get("thread_subject") and not row.get("thread_subject"):
                    row["thread_subject"] = thread_context["thread_subject"]

            try:
                start_gen = time.perf_counter()
                email_content = _message_for_row(row, sender_profile)
                gen_seconds += time.perf_counter() - start_gen

                subject, body = _parse_email_content(email_content)
                reply_to_message_id = thread_context.get("last_message_id", "") if touch_number > 0 else ""
                references = thread_context.get("references", []) if touch_number > 0 else []
                tracking_token = (
                    secrets.token_urlsafe(18)
                    if sender_profile.get("open_tracking_enabled") and sender_profile.get("tracking_base_url")
                    else ""
                )
                quality = assess_email_quality(subject, body)
                if sender_profile.get("spam_guard_enabled") and int(quality["score"]) < 60:
                    skipped += 1
                    reason = "Spam guard blocked send"
                    if quality["flags"]:
                        reason = f"{reason}: {', '.join(quality['flags'])}"
                    _record_skip(row, subject=subject, reason=reason)
                    record_campaign_progress(skipped=1)
                    print(f"[worker-{worker_id}] Skipped {email or 'unknown'}: {reason}")
                    continue

                start_send = time.perf_counter()
                message_id = sender.send(
                    email,
                    subject,
                    body,
                    _sender_name(sender_profile),
                    _agency_name(sender_profile),
                    reply_to_message_id=reply_to_message_id,
                    references=references,
                    tracking_pixel_url=_tracking_pixel_url(sender_profile, tracking_token),
                )
                send_seconds += time.perf_counter() - start_send

                _record_success(
                    row,
                    subject=subject,
                    body=body,
                    message_id=message_id,
                    in_reply_to=reply_to_message_id,
                    tracking_token=tracking_token,
                    copy_quality_score=int(quality["score"]),
                    copy_quality_flags=",".join(quality["flags"]),
                    settings=settings,
                )
                record_campaign_progress(sent=1)
                sent += 1
                print(f"[worker-{worker_id}] Sent {touch_type} to: {email}")
            except Exception as exc:
                failed += 1
                # ✓ Classify bounce type for better error tracking
                bounce_type = classify_bounce(str(exc))
                error_msg = f"[{bounce_type}] {str(exc)}"
                _record_failure(row, subject=default_subject, error_message=error_msg)
                record_campaign_progress(failed=1)
                print(f"[worker-{worker_id}] Failed {touch_type} for {email or 'unknown'}: {exc}")

            # ✓ Add minimum delay to avoid GMail throttling (default: 2 seconds)
            delay = max(DELAY_BETWEEN_EMAILS, 2) if sent > 0 else DELAY_BETWEEN_EMAILS
            if delay > 0:
                time.sleep(delay)

    return {
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "gen_seconds": gen_seconds,
        "send_seconds": send_seconds,
    }


def run_campaign(use_csv_fallback=True, only_unsent=True):
    """Send outreach items for new leads and any due follow-ups."""
    queue, settings = _load_outreach_queue(use_csv_fallback=use_csv_fallback)
    sender_profile = get_sender_profile()
    if not queue:
        finish_campaign(message="Campaign finished: no pending leads or due follow-ups.")
        return

    worker_count = max(1, min(MAX_CONCURRENT_EMAILS, len(queue)))
    chunks = _split_chunks(queue, worker_count)

    started_at = time.perf_counter()
    total_sent = 0
    total_skipped = 0
    total_failed = 0
    total_gen_seconds = 0.0
    total_send_seconds = 0.0

    if worker_count == 1:
        result = _process_chunk(1, chunks[0], settings, sender_profile)
        total_sent += result["sent"]
        total_skipped += result["skipped"]
        total_failed += result["failed"]
        total_gen_seconds += result["gen_seconds"]
        total_send_seconds += result["send_seconds"]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(_process_chunk, idx + 1, chunk, settings, sender_profile)
                for idx, chunk in enumerate(chunks)
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                total_sent += result["sent"]
                total_skipped += result["skipped"]
                total_failed += result["failed"]
                total_gen_seconds += result["gen_seconds"]
                total_send_seconds += result["send_seconds"]

    elapsed = max(0.001, time.perf_counter() - started_at)
    throughput = total_sent / elapsed
    finish_campaign(
        elapsed_seconds=elapsed,
        message=(
            f"Campaign finished: sent={total_sent}, skipped={total_skipped}, failed={total_failed}, "
            f"elapsed={elapsed:.2f}s."
        ),
    )
    print(
        f"Campaign complete: sent={total_sent}, skipped={total_skipped}, failed={total_failed}, "
        f"workers={worker_count}, elapsed={elapsed:.2f}s, throughput={throughput:.2f} emails/sec, "
        f"gen_time={total_gen_seconds:.2f}s, send_time={total_send_seconds:.2f}s"
    )
