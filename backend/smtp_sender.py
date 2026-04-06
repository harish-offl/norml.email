import smtplib
import socket
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from backend.config import (
    SMTP_SERVER,
    SMTP_PORT,
    SMTP_MAX_RETRIES,
    SMTP_RETRY_DELAY_SECONDS,
    get_email_credentials,
    validate_smtp_config,
)


def build_html_email(subject, plain_body, sender_name, agency_name):
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
          You received this email because your business was identified as a potential fit.<br>
          To unsubscribe, reply with "unsubscribe".
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


class SMTPSender:
    """Reusable SMTP connection for faster multi-email sending."""

    def __init__(self):
        self.server       = None
        self.email_address = None

    def connect(self):
        if self.server is not None:
            return

        # Re-read config fresh every time — avoids stale module-level values
        from backend.env_utils import load_project_env
        load_project_env(override=True)

        import os
        smtp_host = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip()
        smtp_port = int(os.getenv("SMTP_PORT", "587"))

        # Validate config before attempting connection
        validate_smtp_config()

        email_address, email_password = get_email_credentials()
        self.email_address = email_address

        # Log connection attempt (never log the password)
        print(f"[SMTP] Connecting to {smtp_host}:{smtp_port} as {email_address}")

        try:
            self.server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            self.server.ehlo()

            # STARTTLS required for port 587
            if smtp_port == 587:
                self.server.starttls()
                self.server.ehlo()

            self.server.login(email_address, email_password)
            print(f"[SMTP] ✓ Authenticated successfully as {email_address}")

        except smtplib.SMTPAuthenticationError:
            self.server = None
            raise RuntimeError(
                "Gmail authentication failed. Use a Gmail App Password, not your regular password. "
                "Generate one at: myaccount.google.com → Security → App Passwords"
            )
        except (smtplib.SMTPConnectError, TimeoutError, socket.timeout, OSError) as e:
            self.server = None
            err_str = str(e)
            if "10060" in err_str or "timed out" in err_str.lower():
                raise RuntimeError(
                    f"Connection to {smtp_host}:{smtp_port} timed out (error 10060). "
                    "Your network or firewall is blocking outbound port 587. "
                    "Try: disable VPN, check Windows Firewall, or test on a mobile hotspot."
                )
            raise RuntimeError(f"SMTP connection failed ({smtp_host}:{smtp_port}): {e}")
        except Exception as e:
            self.server = None
            raise RuntimeError(f"SMTP error: {e}")

    def close(self):
        if self.server is None:
            return
        try:
            self.server.quit()
        except Exception:
            pass
        finally:
            self.server       = None
            self.email_address = None

    def send(self, to_email, subject, body, sender_name="", agency_name=""):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["To"]      = to_email

        html_body = build_html_email(subject, body, sender_name, agency_name)
        msg.attach(MIMEText(body,      "plain"))
        msg.attach(MIMEText(html_body, "html"))

        attempts   = SMTP_MAX_RETRIES + 1
        last_error = None

        for attempt in range(attempts):
            try:
                self.connect()
                if "From" in msg:
                    msg.replace_header(
                        "From",
                        f'"{sender_name}" <{self.email_address}>' if sender_name else self.email_address
                    )
                else:
                    msg["From"] = (
                        f'"{sender_name}" <{self.email_address}>' if sender_name else self.email_address
                    )
                self.server.sendmail(self.email_address, to_email, msg.as_string())
                return

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
        sender.send(to_email, subject, body, sender_name, agency_name)
