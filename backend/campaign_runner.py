import concurrent.futures
import csv
import threading
import time

from backend.ai_engine import generate_cold_email
from backend.app.campaign_status import finish_campaign, record_campaign_progress
from backend.app.crud import list_campaign_leads, update_lead_delivery
from backend.config import DELAY_BETWEEN_EMAILS, MAX_CONCURRENT_EMAILS
from backend.env_utils import BASE_DIR, DATA_DIR
from backend.smtp_sender import SMTPSender


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


def _deduplicate_leads(leads):
    unique_leads = []
    seen_emails = set()

    for row in leads:
        email = (row.get("email") or "").strip().lower()
        if not email or email in seen_emails:
            continue

        normalized_row = dict(row)
        normalized_row["email"] = email
        unique_leads.append(normalized_row)
        seen_emails.add(email)

    return unique_leads


def _load_leads(use_csv_fallback=True, only_unsent=True):
    leads = list_campaign_leads(only_unsent=only_unsent)

    if not leads and use_csv_fallback:
        try:
            csv_path = DATA_DIR / "leads.csv"
            if not csv_path.exists():
                csv_path = BASE_DIR / "leads.csv"
            with open(csv_path, encoding="utf-8") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    leads.append(row)
        except FileNotFoundError:
            print("No leads.csv file found and no leads in database")
            return
    elif not leads:
        print("No leads found in database; campaign not started")
        return

    return _deduplicate_leads(leads)


def _split_chunks(items, chunk_count):
    chunk_count = max(1, min(chunk_count, len(items)))
    chunks = [[] for _ in range(chunk_count)]
    for idx, item in enumerate(items):
        chunks[idx % chunk_count].append(item)
    return [chunk for chunk in chunks if chunk]


def _update_lead_delivery(email, *, last_status, last_error="", sent=False):
    if not email:
        return

    with _lead_update_lock:
        update_lead_delivery(
            email,
            last_status=last_status,
            last_error=last_error,
            sent=sent,
        )


def _mark_lead_sent(email):
    _update_lead_delivery(email, last_status="sent", last_error="", sent=True)


def _mark_lead_failed(email, error_message):
    _update_lead_delivery(email, last_status="failed", last_error=error_message)


def _mark_lead_skipped(email, reason):
    _update_lead_delivery(email, last_status="skipped", last_error=reason)


def _process_chunk(worker_id, rows):
    sent = 0
    skipped = 0
    failed = 0
    gen_seconds = 0.0
    send_seconds = 0.0

    with SMTPSender() as sender:
        for row in rows:
            email = (row.get("email") or "").strip().lower()
            solution = (row.get("niche") or "").strip()
            if not solution:
                skipped += 1
                _mark_lead_skipped(email, "Missing solution/niche")
                record_campaign_progress(skipped=1)
                print(f"[worker-{worker_id}] Skipped {email or 'unknown'}: missing solution/niche")
                continue

            try:
                start_gen = time.perf_counter()
                email_content = generate_cold_email(row)
                gen_seconds += time.perf_counter() - start_gen

                start_send = time.perf_counter()
                subject, body = _parse_email_content(email_content)
                sender.send(email, subject, body)
                send_seconds += time.perf_counter() - start_send

                _mark_lead_sent(email)
                record_campaign_progress(sent=1)
                sent += 1
                print(f"[worker-{worker_id}] Email sent to: {email}")
            except Exception as exc:
                failed += 1
                _mark_lead_failed(email, str(exc))
                record_campaign_progress(failed=1)
                print(f"[worker-{worker_id}] Failed {email or 'unknown'}: {exc}")

            if DELAY_BETWEEN_EMAILS > 0:
                time.sleep(DELAY_BETWEEN_EMAILS)

    return {
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "gen_seconds": gen_seconds,
        "send_seconds": send_seconds,
    }


def run_campaign(use_csv_fallback=True, only_unsent=True):
    """Send generated cold emails to leads with parallel workers."""
    leads = _load_leads(use_csv_fallback=use_csv_fallback, only_unsent=only_unsent)
    if not leads:
        finish_campaign(message="Campaign finished: no pending leads to send.")
        return

    worker_count = max(1, min(MAX_CONCURRENT_EMAILS, len(leads)))
    chunks = _split_chunks(leads, worker_count)

    started_at = time.perf_counter()
    total_sent = 0
    total_skipped = 0
    total_failed = 0
    total_gen_seconds = 0.0
    total_send_seconds = 0.0

    if worker_count == 1:
        result = _process_chunk(1, chunks[0])
        total_sent += result["sent"]
        total_skipped += result["skipped"]
        total_failed += result["failed"]
        total_gen_seconds += result["gen_seconds"]
        total_send_seconds += result["send_seconds"]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(_process_chunk, idx + 1, chunk)
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
