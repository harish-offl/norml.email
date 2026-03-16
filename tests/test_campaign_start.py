import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.app.settings")

import django
from rest_framework.test import APIRequestFactory


django.setup()

from backend.app.main import LeadViewSet  # noqa: E402


class _PendingLeadQuerySetStub:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class _LeadManagerStub:
    def __init__(self, *, exists=True, pending_count=1):
        self._exists = exists
        self._pending_count = pending_count

    def exists(self):
        return self._exists

    def filter(self, **kwargs):
        assert kwargs == {"sent_at__isnull": True}
        return _PendingLeadQuerySetStub(self._pending_count)


class _ThreadStub:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


def test_start_campaign_returns_400_when_smtp_settings_are_missing(monkeypatch):
    factory = APIRequestFactory()
    thread_calls = []

    def thread_factory(target, daemon):
        thread = _ThreadStub(target=target, daemon=daemon)
        thread_calls.append(thread)
        return thread

    monkeypatch.setattr("backend.app.main.Lead.objects", _LeadManagerStub(exists=True, pending_count=2))
    monkeypatch.setattr("backend.app.main.campaign_is_running", lambda: False)
    monkeypatch.setattr("backend.app.main.get_missing_smtp_settings", lambda: ["EMAIL_ADDRESS", "EMAIL_PASSWORD"])
    monkeypatch.setattr("backend.app.main.threading.Thread", thread_factory)

    view = LeadViewSet.as_view({"post": "start_campaign"})
    response = view(factory.post("/api/campaign/start/"))

    assert response.status_code == 400
    assert "EMAIL_ADDRESS" in response.data["error"]
    assert "EMAIL_PASSWORD" in response.data["error"]
    assert thread_calls == []


def test_start_campaign_returns_400_when_all_leads_were_already_sent(monkeypatch):
    factory = APIRequestFactory()

    monkeypatch.setattr("backend.app.main.Lead.objects", _LeadManagerStub(exists=True, pending_count=0))
    monkeypatch.setattr("backend.app.main.campaign_is_running", lambda: False)

    view = LeadViewSet.as_view({"post": "start_campaign"})
    response = view(factory.post("/api/campaign/start/"))

    assert response.status_code == 400
    assert "already been emailed" in response.data["error"]


def test_start_campaign_returns_409_when_campaign_is_already_running(monkeypatch):
    factory = APIRequestFactory()

    monkeypatch.setattr("backend.app.main.Lead.objects", _LeadManagerStub(exists=True, pending_count=2))
    monkeypatch.setattr("backend.app.main.campaign_is_running", lambda: True)
    monkeypatch.setattr(
        "backend.app.main.get_campaign_status_snapshot",
        lambda: {"status": "running", "processed": 1, "total": 2},
    )

    view = LeadViewSet.as_view({"post": "start_campaign"})
    response = view(factory.post("/api/campaign/start/"))

    assert response.status_code == 409
    assert response.data["campaign"]["status"] == "running"


def test_start_campaign_starts_background_thread_when_smtp_settings_exist(monkeypatch):
    factory = APIRequestFactory()
    thread_calls = []

    def thread_factory(target, daemon):
        thread = _ThreadStub(target=target, daemon=daemon)
        thread_calls.append(thread)
        return thread

    monkeypatch.setattr("backend.app.main.Lead.objects", _LeadManagerStub(exists=True, pending_count=2))
    monkeypatch.setattr("backend.app.main.campaign_is_running", lambda: False)
    monkeypatch.setattr("backend.app.main.get_missing_smtp_settings", lambda: [])
    monkeypatch.setattr(
        "backend.app.main.start_campaign_tracking",
        lambda total: (True, {"status": "running", "total": total, "processed": 0}),
    )
    monkeypatch.setattr("backend.app.main.threading.Thread", thread_factory)

    view = LeadViewSet.as_view({"post": "start_campaign"})
    response = view(factory.post("/api/campaign/start/"))

    assert response.status_code == 200
    assert response.data["status"] == "campaign started"
    assert response.data["campaign"]["total"] == 2
    assert len(thread_calls) == 1
    assert thread_calls[0].daemon is True
    assert thread_calls[0].started is True


def test_campaign_status_returns_latest_snapshot(monkeypatch):
    factory = APIRequestFactory()
    snapshot = {"status": "finished", "sent": 3, "failed": 0}

    monkeypatch.setattr("backend.app.main.get_campaign_status_snapshot", lambda: snapshot)

    view = LeadViewSet.as_view({"get": "campaign_status"})
    response = view(factory.get("/api/campaign/status/"))

    assert response.status_code == 200
    assert response.data == snapshot
