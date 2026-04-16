import email
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr

from backend.app.crud import get_lead_by_email, mark_reply_received, record_reply_sync_completed
from backend.config import IMAP_PORT, IMAP_SERVER, REPLY_SYNC_LOOKBACK_DAYS, get_imap_credentials


MESSAGE_ID_RE = re.compile(r"<[^>]+>")


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return str(value).strip()


def _extract_message_ids(value: str | None) -> list[str]:
    if not value:
        return []
    return [match.group(0).strip() for match in MESSAGE_ID_RE.finditer(str(value))]


def _normalize_subject(value: str | None) -> str:
    subject = _decode_header_value(value)
    while subject.lower().startswith("re:"):
        subject = subject[3:].strip()
    return subject


def _html_to_text(value: str) -> str:
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", value or "", flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_text_body(message) -> str:
    if message.is_multipart():
        preferred = []
        fallback = []
        for part in message.walk():
            content_type = str(part.get_content_type() or "").lower()
            disposition = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except Exception:
                text = payload.decode("utf-8", errors="replace")
            if content_type == "text/plain":
                preferred.append(text)
            elif content_type == "text/html":
                fallback.append(_html_to_text(text))
        body = "\n".join(preferred).strip() or "\n".join(fallback).strip()
    else:
        payload = message.get_payload(decode=True)
        if payload is None:
            body = ""
        else:
            charset = message.get_content_charset() or "utf-8"
            try:
                body = payload.decode(charset, errors="replace")
            except Exception:
                body = payload.decode("utf-8", errors="replace")
            if str(message.get_content_type() or "").lower() == "text/html":
                body = _html_to_text(body)

    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith(">") or stripped.lower().startswith("on ") and "wrote:" in stripped.lower():
            break
        lines.append(stripped)
    cleaned = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)[:1000]


def _classify_reply(message, body: str) -> str:
    lowered = (body or "").lower()
    auto_submitted = str(message.get("Auto-Submitted") or "").lower()
    precedence = str(message.get("Precedence") or "").lower()

    if "auto-replied" in auto_submitted or "out of office" in lowered or "away from the office" in lowered:
        return "auto_reply"
    if "unsubscribe" in lowered or "remove me" in lowered or "take me off" in lowered:
        return "unsubscribe"
    if "not interested" in lowered or "no thanks" in lowered or "stop emailing" in lowered:
        return "not_interested"
    if "let's talk" in lowered or "lets talk" in lowered or "interested" in lowered or "send me" in lowered:
        return "interested"
    if "later" in lowered or "next quarter" in lowered or "not now" in lowered:
        return "not_now"
    if "bulk" in precedence:
        return "auto_reply"
    return "unknown"


def _subject_matches(lead: dict, subject: str) -> bool:
    thread_subject = _normalize_subject(lead.get("thread_subject"))
    normalized_subject = _normalize_subject(subject)
    if not normalized_subject:
        return False
    if thread_subject and normalized_subject == thread_subject:
        return True
    return normalized_subject.startswith(thread_subject) if thread_subject else normalized_subject.lower().startswith("re:")


def sync_mailbox_replies(*, limit: int = 50, unread_only: bool = True) -> dict:
    username, password = get_imap_credentials()
    if not username or not password:
        raise RuntimeError("IMAP credentials are missing. Add IMAP_USERNAME/IMAP_PASSWORD or reuse Gmail app password.")

    checked = 0
    matched = 0
    updated = 0
    items = []
    since = (datetime.now(timezone.utc) - timedelta(days=REPLY_SYNC_LOOKBACK_DAYS)).strftime("%d-%b-%Y")

    try:
        with imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT) as mailbox:
            mailbox.login(username, password)
            mailbox.select("INBOX")
            criteria = ["SINCE", since]
            if unread_only:
                criteria.append("UNSEEN")
            status, payload = mailbox.search(None, *criteria)
            if status != "OK":
                raise RuntimeError("Could not search the mailbox for replies.")

            message_ids = [item for item in payload[0].split() if item][-max(1, min(int(limit or 50), 500)) :]
            for message_id in reversed(message_ids):
                status, fetched = mailbox.fetch(message_id, "(BODY.PEEK[])")
                if status != "OK":
                    continue
                raw_message = b""
                for chunk in fetched:
                    if isinstance(chunk, tuple) and len(chunk) >= 2:
                        raw_message = chunk[1]
                        break
                if not raw_message:
                    continue

                checked += 1
                message = email.message_from_bytes(raw_message)
                from_email = parseaddr(message.get("From") or "")[1].strip().lower()
                if not from_email:
                    continue

                lead = get_lead_by_email(from_email)
                if not lead:
                    continue

                references = _extract_message_ids(message.get("References")) + _extract_message_ids(message.get("In-Reply-To"))
                subject = _decode_header_value(message.get("Subject"))
                if not references and not _subject_matches(lead, subject):
                    continue

                matched += 1
                snippet = _extract_text_body(message)
                reply_type = _classify_reply(message, snippet)
                updated_lead = mark_reply_received(
                    email=from_email,
                    reply_type=reply_type,
                    reply_summary=snippet,
                    reference_message_ids=references,
                )
                if not updated_lead:
                    continue

                updated += 1
                items.append(
                    {
                        "lead_email": from_email,
                        "lead_name": updated_lead.get("name") or from_email,
                        "reply_type": reply_type,
                        "reply_summary": snippet,
                        "subject": subject,
                    }
                )
                if unread_only:
                    try:
                        mailbox.store(message_id, "+FLAGS", "\\Seen")
                    except Exception:
                        pass
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Reply sync could not connect to IMAP mailbox {IMAP_SERVER}:{IMAP_PORT}. {exc}") from exc

    record_reply_sync_completed()
    return {
        "checked": checked,
        "matched": matched,
        "updated": updated,
        "unread_only": bool(unread_only),
        "lookback_days": REPLY_SYNC_LOOKBACK_DAYS,
        "items": items[:10],
    }
