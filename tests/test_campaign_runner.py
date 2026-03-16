import os
import sys
import types

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.app.settings")

import django

from backend.campaign_runner import _load_leads, _process_chunk


django.setup()


class _LeadRecord:
    def __init__(self, *, email, sent_at, name="Lead", niche="SEO", industry="", phone="", company=""):
        self.email = email
        self.sent_at = sent_at
        self.name = name
        self.niche = niche
        self.industry = industry
        self.phone = phone
        self.company = company


class _QuerySetStub:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, **kwargs):
        assert kwargs == {"sent_at__isnull": True}
        return _QuerySetStub([item for item in self.items if item.sent_at is None])

    def order_by(self, *args):
        return self

    def iterator(self, chunk_size=None):
        del chunk_size
        return iter(self.items)

    def exists(self):
        return bool(self.items)

    def __iter__(self):
        return iter(self.items)


def test_load_leads_returns_only_unsent_records(monkeypatch):
    records = [
        _LeadRecord(email="fresh@example.com", sent_at=None),
        _LeadRecord(email="already-sent@example.com", sent_at="2026-03-16T09:00:00Z"),
    ]
    fake_module = types.SimpleNamespace(
        Lead=types.SimpleNamespace(objects=types.SimpleNamespace(all=lambda: _QuerySetStub(records)))
    )

    monkeypatch.setitem(sys.modules, "backend.app.models", fake_module)

    leads = _load_leads(use_csv_fallback=False, only_unsent=True)

    assert [lead["email"] for lead in leads] == ["fresh@example.com"]


def test_process_chunk_marks_delivery_progress(monkeypatch):
    sent_messages = []
    state_changes = []
    progress_updates = []

    class _DummySender:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def send(self, to_email, subject, body):
            sent_messages.append((to_email, subject, body))

    monkeypatch.setattr("backend.campaign_runner.SMTPSender", lambda: _DummySender())
    monkeypatch.setattr("backend.campaign_runner.generate_cold_email", lambda row: "Subject: Hello\nBody")
    monkeypatch.setattr("backend.campaign_runner._mark_lead_sent", lambda email: state_changes.append(("sent", email)))
    monkeypatch.setattr(
        "backend.campaign_runner._mark_lead_skipped",
        lambda email, reason: state_changes.append(("skipped", email, reason)),
    )
    monkeypatch.setattr(
        "backend.campaign_runner._mark_lead_failed",
        lambda email, error: state_changes.append(("failed", email, error)),
    )
    monkeypatch.setattr(
        "backend.campaign_runner.record_campaign_progress",
        lambda **kwargs: progress_updates.append(kwargs),
    )
    monkeypatch.setattr("backend.campaign_runner.DELAY_BETWEEN_EMAILS", 0)

    result = _process_chunk(
        1,
        [
            {"email": "fresh@example.com", "name": "Fresh", "niche": "SEO"},
            {"email": "missing@example.com", "name": "Missing", "niche": ""},
        ],
    )

    assert (result["sent"], result["skipped"], result["failed"]) == (1, 1, 0)
    assert sent_messages[0][0] == "fresh@example.com"
    assert ("sent", "fresh@example.com") in state_changes
    assert ("skipped", "missing@example.com", "Missing solution/niche") in state_changes
    assert progress_updates == [{"sent": 1}, {"skipped": 1}]
    assert result["gen_seconds"] >= 0
    assert result["send_seconds"] >= 0
