"""URL configuration and API views for the email automation project."""

import csv
import io
import logging
import os
import re
import threading

from django.http import FileResponse, JsonResponse, HttpResponse
from django.urls import path
from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from backend.campaign_runner import run_campaign
from backend.config import get_missing_smtp_settings
from backend.env_utils import BASE_DIR
from .campaign_status import (
    campaign_is_running,
    fail_campaign,
    get_campaign_status_snapshot,
    start_campaign_tracking,
)
from .models import Lead


logger = logging.getLogger(__name__)


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


def _normalize_header(header):
    return re.sub(r"[^a-z0-9]+", " ", (header or "").strip().lower()).strip()


def _parse_bool(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _count_pending_leads():
    return Lead.objects.filter(sent_at__isnull=True).count()


def _canonicalize_row(row):
    normalized = {}
    ignored = []
    for key, value in row.items():
        canonical_key = CSV_FIELD_ALIASES.get(_normalize_header(key))
        if not canonical_key:
            ignored.append(key)
            continue
        normalized[canonical_key] = (value or "").strip()
    return normalized, ignored


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = "__all__"


class LeadViewSet(viewsets.ModelViewSet):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    parser_classes = (MultiPartParser,)

    @action(detail=False, methods=["post"])
    def upload(self, request):
        """Upload a CSV file of leads."""
        file = request.FILES.get("file")
        if not file:
            return Response({"error": "No file provided"}, status=400)

        try:
            content = file.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            replace_existing = _parse_bool(request.data.get("replace_existing"), default=True)
            require_solution = _parse_bool(request.data.get("require_solution"), default=True)
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
                if require_solution and not cleaned_row.get("niche"):
                    skipped += 1
                    continue
                parsed_rows.append(cleaned_row)

            if not parsed_rows:
                return Response(
                    {
                        "error": "No valid rows found. Ensure CSV includes Email and Solution/Interest columns.",
                        "ignored_columns": sorted(ignored_columns),
                        "skipped": skipped,
                    },
                    status=400,
                )

            created = 0
            updated = 0
            with transaction.atomic():
                if replace_existing:
                    Lead.objects.all().delete()

                for row in parsed_rows:
                    defaults = {
                        "name": row.get("name", ""),
                        "niche": row.get("niche", ""),
                        "industry": row.get("industry", ""),
                        "phone": row.get("phone", ""),
                        "company": row.get("company", ""),
                    }
                    lead = Lead.objects.filter(email__iexact=row["email"]).first()
                    if lead:
                        for field_name, field_value in defaults.items():
                            setattr(lead, field_name, field_value)
                        if lead.sent_at is None:
                            lead.last_status = "pending"
                            lead.last_error = ""
                        lead.email = row["email"]
                        lead.save()
                        updated += 1
                    else:
                        Lead.objects.create(email=row["email"], **defaults)
                        created += 1

            return Response(
                {
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                    "replace_existing": replace_existing,
                    "require_solution": require_solution,
                    "ignored_columns": sorted(ignored_columns),
                }
            )
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    @action(detail=False, methods=["post"])
    def start_campaign(self, request):
        """Start a campaign in a background thread."""
        if not Lead.objects.exists():
            return Response({"error": "No leads found. Upload leads before starting a campaign."}, status=400)

        if campaign_is_running():
            return Response(
                {
                    "error": "Campaign is already running.",
                    "campaign": get_campaign_status_snapshot(),
                },
                status=409,
            )

        pending_leads = _count_pending_leads()
        if pending_leads == 0:
            return Response(
                {
                    "error": (
                        "All leads have already been emailed. Upload new leads or replace the existing leads "
                        "to start another campaign."
                    )
                },
                status=400,
            )

        missing_settings = get_missing_smtp_settings()
        if missing_settings:
            missing = ", ".join(missing_settings)
            return Response(
                {
                    "error": (
                        f"Missing SMTP configuration: {missing}. "
                        "Add them to the project .env file or set them in the environment before starting a campaign."
                    )
                },
                status=400,
            )

        started, campaign = start_campaign_tracking(total=pending_leads)
        if not started:
            return Response(
                {
                    "error": "Campaign is already running.",
                    "campaign": campaign,
                },
                status=409,
            )

        def task():
            try:
                run_campaign(use_csv_fallback=False, only_unsent=True)
            except Exception as exc:
                fail_campaign(str(exc))
                logger.exception("Campaign thread crashed")

        threading.Thread(target=task, daemon=True).start()
        return Response({"status": "campaign started", "campaign": campaign})

    @action(detail=False, methods=["get"])
    def campaign_status(self, request):
        """Return the latest background campaign status."""
        return Response(get_campaign_status_snapshot())


def frontend_view(request):
    """Serve the simple frontend page."""
    frontend_path = BASE_DIR / "frontend" / "index.html"
    if frontend_path.exists():
        return FileResponse(open(frontend_path, "rb"), content_type="text/html")
    return JsonResponse({"error": "Frontend not found"}, status=404)


def favicon_view(request):
    """Silence favicon requests in dev if no icon is present."""
    return HttpResponse(status=204)


urlpatterns = [
    path("api/leads/", LeadViewSet.as_view({"get": "list", "post": "create"})),
    path("api/leads/upload/", LeadViewSet.as_view({"post": "upload"})),
    path("api/campaign/start/", LeadViewSet.as_view({"post": "start_campaign"})),
    path("api/campaign/status/", LeadViewSet.as_view({"get": "campaign_status"})),
    path("", frontend_view),
    path("favicon.ico", favicon_view),
]
