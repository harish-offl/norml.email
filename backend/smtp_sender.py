import smtplib
import socket
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid

from backend.config import (
    SMTP_MAX_RETRIES,
    SMTP_RETRY_DELAY_SECONDS,
    get_email_credentials,
)


def _get_smtp_config():
    """Read SMTP config fresh every time — avoids stale module-level values."""
    from backend.env_utils import load_project_env
    import os
    load_project_env(override=True)
    host = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "465"))
    return host, port


def build_html_email(subject, plain_body, sender_name, agency_name, sender_email=""):
    """Convert plain text email (with '- ' bullets) into proper HTML with <ul><li> tags."""
    sections = []
    bullet_buffer = []

    for line in plain_body.strip().split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            bullet_buffer.append(stripped[2:])
        else:
            if bullet_buffer:
                items = "".join(f"<li>{b}</li>" for b in bullet_buffer)
                sections.append(
                    f'<ul style="margin:0 0 16px 0;padding-left:20px;'
                    f'font-size:15px;line-height:2;color:#374151">{items}</ul>'
                )
                bullet_buffer = []
            if not stripped:
                continue
            if stripped.lower().startswith("best regards"):
                sections.append(
                    f'<p style="margin:0 0 4px 0;font-size:15px;color:#374151">Best regards,</p>'
                    f'<p style="margin:0 0 20px 0;font-size:15px;font-weight:700;color:#222222">{sender_name}</p>'
                )
            elif stripped.lower().startswith("p.s."):
                sections.append(
                    f'<p style="margin:16px 0 0 0;font-size:13px;color:#6b7280;font-style:italic">{stripped}</p>'
                )
            else:
                sections.append(
                    f'<p style="margin:0 0 16px 0;font-size:15px;line-height:1.7;color:#374151">{stripped}</p>'
                )

    if bullet_buffer:
        items = "".join(f"<li>{b}</li>" for b in bullet_buffer)
        sections.append(
            f'<ul style="margin:0 0 16px 0;padding-left:20px;'
            f'font-size:15px;line-height:2;color:#374151">{items}</ul>'
        )

    body_html = "\n        ".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif;color:#222222">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff">
  <tr><td align="center" style="padding:40px 20px">
    <table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%">
      <tr><td style="padding:0 0 20px 0;border-bottom:2px solid #ff6a00">
        <span style="font-size:13px;font-weight:700;color:#ff6a00;letter-spacing:1px;text-transform:uppercase">{agency_name}</span>
      </td></tr>
      <tr><td style="padding:28px 0 0 0">
        {body_html}
      </td></tr>
      <tr><td style="padding:24px 0 0 0;border-top:1px solid #e5e7eb">
        <p style="margin:0;font-size:11px;color:#9ca3af;line-height:1.6">
          You received this email from {agency_name} because your business matched our ideal customer profile.<br>
          <a href="mailto:{sender_email}?subject=unsubscribe" style="color:#ff6a00;text-decoration:none;font-weight:500;">Unsubscribe</a> | 
          <a href="mailto:{sender_email}?subject=do+not+contact" style="color:#ff6a00;text-decoration:none;font-weight:500;">Do not contact</a>
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def _connect_smtp(host, port, email_address, email_password):
    """
    Connect to SMTP. Uses unverified SSL context to bypass Windows CA cert issues.
    Port 465 → SMTP_SSL (direct SSL)
    Port 587 → SMTP + STARTTLS
    Auto-fallback between ports.
    """
    # Use unverified context — fixes Windows SSL cert chain errors
    ctx = ssl._create_unverified_context()

    def try_ssl(h, p):
        print(f"[SMTP] Trying SSL on {h}:{p}")
        server = smtplib.SMTP_SSL(h, p, timeout=30, context=ctx)
        server.ehlo()
        server.login(email_address, email_password)
        print(f"[SMTP] ✓ Connected via SSL as {email_address}")
        return server

    def try_starttls(h, p):
        print(f"[SMTP] Trying STARTTLS on {h}:{p}")
        server = smtplib.SMTP(h, p, timeout=30)
        server.ehlo()
        server.starttls(context=ctx)
        server.ehlo()
        server.login(email_address, email_password)
        print(f"[SMTP] ✓ Connected via STARTTLS as {email_address}")
        return server

    # Primary attempt
    try:
        if port == 465:
            return try_ssl(host, port)
        else:
            return try_starttls(host, port)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError(
            "Gmail authentication failed. "
            "Use a Gmail App Password (not your regular password). "
            "Generate one at: myaccount.google.com → Security → App Passwords"
        )
    except Exception as primary_err:
        print(f"[SMTP] Primary port {port} failed: {primary_err}. Trying fallback...")

    # Fallback to the other port
    fallback_port = 587 if port == 465 else 465
    try:
        if fallback_port == 465:
            return try_ssl(host, fallback_port)
        else:
            return try_starttls(host, fallback_port)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError(
            "Gmail authentication failed. "
            "Use a Gmail App Password (not your regular password). "
            "Generate one at: myaccount.google.com → Security → App Passwords"
        )
    except Exception as fallback_err:
        raise RuntimeError(
            f"Cannot connect to {host} on port {port} or {fallback_port}. "
            f"Details: {fallback_err}"
        )


class SMTPSender:
    """Reusable SMTP connection for faster multi-email sending."""

    def __init__(self):
        self.server        = None
        self.email_address = None

    def connect(self):
        if self.server is not None:
            return

        host, port = _get_smtp_config()
        email_address, email_password = get_email_credentials()

        if not email_address or not email_password:
            raise RuntimeError(
                "EMAIL_ADDRESS or EMAIL_PASSWORD not set. "
                "Check your .env file."
            )

        self.email_address = email_address
        self.server = _connect_smtp(host, port, email_address, email_password)

    def close(self):
        if self.server is None:
            return
        try:
            self.server.quit()
        except Exception:
            pass
        finally:
            self.server        = None
            self.email_address = None

    def send(
        self,
        to_email,
        subject,
        body,
        sender_name="",
        agency_name="",
        reply_to_message_id="",
        references=None,
    ):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["To"]      = to_email
        message_id = make_msgid()
        msg["Message-ID"] = message_id
        if reply_to_message_id:
            msg["In-Reply-To"] = reply_to_message_id
        if references:
            if isinstance(references, (list, tuple)):
                references_value = " ".join(ref for ref in references if ref)
            else:
                references_value = str(references).strip()
            if references_value:
                msg["References"] = references_value

        html_body = build_html_email(subject, body, sender_name, agency_name, self.email_address)
        msg.attach(MIMEText(body,      "plain"))
        msg.attach(MIMEText(html_body, "html"))

        attempts   = SMTP_MAX_RETRIES + 1
        last_error = None

        for attempt in range(attempts):
            try:
                self.connect()
                from_header = (
                    f'"{sender_name}" <{self.email_address}>'
                    if sender_name else self.email_address
                )
                if "From" in msg:
                    msg.replace_header("From", from_header)
                else:
                    msg["From"] = from_header
                self.server.sendmail(self.email_address, to_email, msg.as_string())
                return message_id
            except Exception as exc:
                last_error = exc
                self.close()
                if attempt < attempts - 1:
                    time.sleep(SMTP_RETRY_DELAY_SECONDS)

        raise RuntimeError(f"Failed to send to {to_email}: {last_error}")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def send_email(to_email, subject, body, sender_name="", agency_name=""):
    """Backward-compatible single send API."""
    with SMTPSender() as sender:
        return sender.send(to_email, subject, body, sender_name, agency_name)
