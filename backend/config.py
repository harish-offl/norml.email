import os
import re

from backend.env_utils import load_project_env

# Always load with override=True so .env values win over stale system env vars
load_project_env(override=True)

# ── SMTP config ───────────────────────────────────────────────────────────────
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip()
SMTP_PORT   = int(os.getenv("SMTP_PORT", "587"))

# ── Campaign tuning ───────────────────────────────────────────────────────────
DELAY_BETWEEN_EMAILS   = float(os.getenv("DELAY_BETWEEN_EMAILS", "0"))
MAX_CONCURRENT_EMAILS  = max(1, int(os.getenv("MAX_CONCURRENT_EMAILS", "2")))
SMTP_MAX_RETRIES       = max(0, int(os.getenv("SMTP_MAX_RETRIES", "1")))
SMTP_RETRY_DELAY_SECONDS = float(os.getenv("SMTP_RETRY_DELAY_SECONDS", "1"))
LEAD_FETCH_CHUNK_SIZE  = max(100, int(os.getenv("LEAD_FETCH_CHUNK_SIZE", "500")))


def _clean_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def get_email_credentials() -> tuple[str | None, str | None]:
    """Always re-read from env so runtime changes are picked up."""
    load_project_env(override=True)
    return _clean_env("EMAIL_ADDRESS"), _clean_env("EMAIL_PASSWORD")


def get_missing_smtp_settings() -> list[str]:
    email_address, email_password = get_email_credentials()
    missing = []
    if not email_address:
        missing.append("EMAIL_ADDRESS")
    if not email_password:
        missing.append("EMAIL_PASSWORD")
    return missing


def validate_smtp_config() -> None:
    """
    Validate SMTP config at startup.
    Raises RuntimeError with a clear message if anything is wrong.
    """
    load_project_env(override=True)

    server = os.getenv("SMTP_SERVER", "").strip()
    port_str = os.getenv("SMTP_PORT", "587").strip()
    email, password = get_email_credentials()

    errors = []

    # Must not be an IP address — Gmail requires hostname for TLS SNI
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", server):
        errors.append(
            f"SMTP_SERVER is set to an IP address ({server}). "
            "Use the hostname 'smtp.gmail.com' instead — "
            "Gmail requires the hostname for TLS SNI negotiation."
        )
    elif not server:
        errors.append("SMTP_SERVER is not set. Add SMTP_SERVER=smtp.gmail.com to your .env file.")

    try:
        port = int(port_str)
        if port not in (587, 465, 25):
            errors.append(f"SMTP_PORT={port} is unusual. Expected 587 (STARTTLS) or 465 (SSL).")
    except ValueError:
        errors.append(f"SMTP_PORT='{port_str}' is not a valid integer.")

    if not email:
        errors.append("EMAIL_ADDRESS is not set. Add it to your .env file.")
    if not password:
        errors.append("EMAIL_PASSWORD is not set. Add your Gmail App Password to .env.")

    if errors:
        raise RuntimeError(
            "SMTP configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        )


def smtp_preflight_test() -> str:
    """
    Test SMTP connection before campaign starts.
    Returns 'ok' on success, raises RuntimeError with clear message on failure.
    """
    import smtplib
    import socket

    validate_smtp_config()

    server = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip()
    port   = int(os.getenv("SMTP_PORT", "587"))
    email, password = get_email_credentials()

    print(f"[SMTP preflight] host={server} port={port} user={email}")

    try:
        with smtplib.SMTP(server, port, timeout=15) as conn:
            conn.ehlo()
            if port == 587:
                conn.starttls()
                conn.ehlo()
            conn.login(email, password)
        print("[SMTP preflight] ✓ Connection successful")
        return "ok"

    except smtplib.SMTPAuthenticationError:
        raise RuntimeError(
            "Gmail authentication failed. "
            "Make sure you are using a Gmail App Password (not your regular password). "
            "Generate one at: myaccount.google.com → Security → App Passwords"
        )
    except smtplib.SMTPConnectError as e:
        raise RuntimeError(
            f"Cannot connect to {server}:{port}. "
            "Check your internet connection and firewall. "
            f"Detail: {e}"
        )
    except TimeoutError:
        raise RuntimeError(
            f"Connection to {server}:{port} timed out (error 10060). "
            "Your network or firewall is blocking outbound port 587. "
            "Try: disable VPN, check Windows Firewall, or use a mobile hotspot to test."
        )
    except socket.gaierror:
        raise RuntimeError(
            f"Cannot resolve hostname '{server}'. "
            "Check your internet connection or DNS settings."
        )
    except Exception as e:
        raise RuntimeError(f"SMTP preflight failed: {e}")
