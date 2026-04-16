"""FastAPI application and API routes for the email automation project."""

import csv
import io
import logging
import re
import threading

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.app.campaign_status import (
    campaign_is_running,
    fail_campaign,
    get_campaign_status_snapshot,
    start_campaign_tracking,
)
from backend.app.crud import (
    bulk_store_leads,
    count_due_followups,
    count_ready_outreach,
    count_pending_leads,
    create_lead,
    get_followup_settings,
    get_lead_by_email,
    get_report_overview,
    get_sender_profile,
    leads_exist,
    list_leads,
    record_open_event,
    update_sender_profile,
    update_followup_settings,
)
from backend.app.database import initialize_database
from backend.app.schemas import FollowupSettingsUpdate, LeadCreate, ReplySyncRequest, SenderProfileUpdate
from backend.campaign_runner import run_campaign
from backend.config import get_missing_smtp_settings, smtp_preflight_test
from backend.env_utils import BASE_DIR
from backend.reply_sync import sync_mailbox_replies


logger = logging.getLogger(__name__)

app = FastAPI(title="AI Email Automation")
app.mount("/frontend", StaticFiles(directory=str(BASE_DIR / "frontend")), name="frontend")

TRACKING_PIXEL_BYTES = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff"
    b"\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00"
    b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


CSV_FIELD_ALIASES = {
    "name": "name",
    "full name": "name",
    "client name": "name",
    "email": "email",
    "e mail": "email",
    "email address": "email",
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "company": "company",
    "company name": "company",
    "industry": "industry",
    "solution": "niche",
    "service": "niche",
    "services": "niche",
    "service offering": "niche",
    "services offered": "niche",
    "offering": "niche",
    "offerings": "niche",
    "interest": "niche",
    "niche": "niche",
}


@app.on_event("startup")
def on_startup() -> None:
    initialize_database()


def _normalize_header(header: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (header or "").strip().lower()).strip()


def _parse_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _canonicalize_row(row: dict) -> tuple[dict, list[str]]:
    normalized = {}
    ignored = []
    for key, value in row.items():
        canonical_key = CSV_FIELD_ALIASES.get(_normalize_header(key))
        if not canonical_key:
            ignored.append(key)
            continue
        normalized[canonical_key] = (value or "").strip()
    return normalized, ignored


def _error(message: str, status_code: int, **extra):
    payload = {"error": message}
    payload.update(extra)
    return JSONResponse(payload, status_code=status_code)


@app.get("/api/leads/")
def list_leads_endpoint():
    return list_leads()


@app.post("/api/leads/", status_code=201)
def create_lead_endpoint(payload: LeadCreate):
    existing = get_lead_by_email(payload.email)
    if existing:
        return _error("Lead with this email already exists.", 409)
    return create_lead(payload.model_dump())


@app.post("/api/leads/upload/")
async def upload_leads(
    file: UploadFile = File(...),
    replace_existing: str = Form("true"),
    require_solution: str = Form("true"),
):
    if not file:
        return _error("No file provided", 400)

    try:
        content = (await file.read()).decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        replace_existing_value = _parse_bool(replace_existing, default=True)
        require_solution_value = _parse_bool(require_solution, default=True)
        parsed_rows = []
        ignored_columns = set()
        skipped = 0

        for row in reader:
            cleaned_row, ignored = _canonicalize_row(row)
            ignored_columns.update(ignored)

            email = (cleaned_row.get("email") or "").strip().lower()
            if not email:
                skipped += 1
                continue

            cleaned_row["email"] = email
            if require_solution_value and not cleaned_row.get("niche"):
                skipped += 1
                continue
            parsed_rows.append(cleaned_row)

        if not parsed_rows:
            return _error(
                "No valid rows found. Ensure CSV includes Email and Solution/Interest columns.",
                400,
                ignored_columns=sorted(ignored_columns),
                skipped=skipped,
            )

        created, updated = bulk_store_leads(
            parsed_rows,
            replace_existing=replace_existing_value,
        )

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "replace_existing": replace_existing_value,
            "require_solution": require_solution_value,
            "ignored_columns": sorted(ignored_columns),
        }
    except Exception as exc:
        return _error(str(exc), 400)


@app.post("/api/campaign/start/")
def start_campaign():
    if not leads_exist():
        return _error("No leads found. Upload leads before starting a campaign.", 400)

    if campaign_is_running():
        return _error(
            "Campaign is already running.",
            409,
            campaign=get_campaign_status_snapshot(),
        )

    followup_settings = get_followup_settings()
    pending_leads = count_pending_leads()
    due_followups = count_due_followups(followup_settings) if followup_settings.get("enabled") else 0
    ready_outreach = count_ready_outreach(followup_settings)
    if ready_outreach == 0:
        return _error(
            "No pending leads or due follow-ups. Upload new leads or wait until the next follow-up window.",
            400,
        )

    missing_settings = get_missing_smtp_settings()
    if missing_settings:
        missing = ", ".join(missing_settings)
        return _error(
            (
                f"Missing SMTP configuration: {missing}. "
                "Add them to the project .env file or set them in the environment before starting a campaign."
            ),
            400,
        )

    # NOTE: preflight removed — it blocks campaign on restricted networks.
    # SMTP errors are caught per-lead and reported in campaign status.

    started, campaign = start_campaign_tracking(total=ready_outreach)
    if not started:
        return _error("Campaign is already running.", 409, campaign=campaign)

    def task():
        try:
            run_campaign(use_csv_fallback=False, only_unsent=True)
        except Exception as exc:
            fail_campaign(str(exc))
            logger.exception("Campaign thread crashed")

    threading.Thread(target=task, daemon=True).start()
    return {
        "status": "campaign started",
        "campaign": campaign,
        "queue": {
            "pending_leads": pending_leads,
            "due_followups": due_followups,
            "total": ready_outreach,
        },
    }


@app.get("/api/campaign/status/")
def campaign_status():
    return get_campaign_status_snapshot()


@app.get("/api/reports/overview/")
def reports_overview(days: int = 30):
    return get_report_overview(days=days)


@app.get("/api/sender/profile/")
def sender_profile():
    return get_sender_profile()


@app.post("/api/sender/profile/")
def update_sender_profile_endpoint(payload: SenderProfileUpdate):
    try:
        return update_sender_profile(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        return _error(str(exc), 400)


@app.post("/api/replies/sync/")
def sync_replies(payload: ReplySyncRequest):
    try:
        return sync_mailbox_replies(limit=payload.limit, unread_only=payload.unread_only)
    except RuntimeError as exc:
        return _error(str(exc), 400)


@app.get("/t/{token}.gif", include_in_schema=False)
def track_email_open(token: str, request: Request):
    record_open_event(
        token,
        remote_addr=(request.client.host if request.client else ""),
        user_agent=request.headers.get("user-agent", ""),
    )
    return Response(
        content=TRACKING_PIXEL_BYTES,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/followups/settings/")
def get_followup_settings_endpoint():
    return get_followup_settings()


@app.get("/api/followups/settings", include_in_schema=False)
def get_followup_settings_endpoint_compat():
    return get_followup_settings()


@app.post("/api/followups/settings/")
def update_followup_settings_endpoint(payload: FollowupSettingsUpdate):
    try:
        return update_followup_settings(payload.model_dump())
    except ValueError as exc:
        return _error(str(exc), 400)


@app.post("/api/followups/settings", include_in_schema=False)
def update_followup_settings_endpoint_compat(payload: FollowupSettingsUpdate):
    try:
        return update_followup_settings(payload.model_dump())
    except ValueError as exc:
        return _error(str(exc), 400)


@app.get("/", response_class=FileResponse)
def frontend_view():
    frontend_path = BASE_DIR / "frontend" / "index.html"
    if frontend_path.exists():
        return FileResponse(
            frontend_path,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return _error("Frontend not found", 404)


@app.get("/favicon.ico")
def favicon_view():
    return Response(status_code=204)
