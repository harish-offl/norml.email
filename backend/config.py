import os

from backend.env_utils import load_project_env


load_project_env()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

DELAY_BETWEEN_EMAILS = float(os.getenv("DELAY_BETWEEN_EMAILS", "10"))
MAX_CONCURRENT_EMAILS = max(1, int(os.getenv("MAX_CONCURRENT_EMAILS", "2")))
SMTP_MAX_RETRIES = max(0, int(os.getenv("SMTP_MAX_RETRIES", "2")))
SMTP_RETRY_DELAY_SECONDS = float(os.getenv("SMTP_RETRY_DELAY_SECONDS", "1.5"))
LEAD_FETCH_CHUNK_SIZE = max(100, int(os.getenv("LEAD_FETCH_CHUNK_SIZE", "500")))


def _clean_env(name):
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def get_email_credentials():
    load_project_env()
    return _clean_env("EMAIL_ADDRESS"), _clean_env("EMAIL_PASSWORD")


def get_missing_smtp_settings():
    email_address, email_password = get_email_credentials()
    missing = []
    if not email_address:
        missing.append("EMAIL_ADDRESS")
    if not email_password:
        missing.append("EMAIL_PASSWORD")
    return missing
