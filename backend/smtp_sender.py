import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from backend.config import (
    SMTP_SERVER,
    SMTP_PORT,
    SMTP_MAX_RETRIES,
    SMTP_RETRY_DELAY_SECONDS,
    get_email_credentials,
)


def build_html_email(subject, plain_body, sender_name, agency_name):
    """Wrap plain text body in a clean professional white HTML email."""
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.7;color:#374151">{p.strip()}</p>'
        for p in plain_body.strip().split("\n\n") if p.strip()
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff">
    <tr><td align="center" style="padding:40px 20px">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">
        <tr><td style="padding:0 0 20px 0;border-bottom:1px solid #e5e7eb">
          <span style="font-size:12px;font-weight:700;color:#ff6a00;letter-spacing:1px;text-transform:uppercase">{agency_name}</span>
        </td></tr>
        <tr><td style="padding:28px 0 0 0">
          {paragraphs}
        </td></tr>
        <tr><td style="padding:28px 0 0 0;border-top:1px solid #e5e7eb;margin-top:28px">
          <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.5">
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
        self.server = None
        self.email_address = None

    def connect(self):
        if self.server is not None:
            return
        email_address, email_password = get_email_credentials()
        if not email_address or not email_password:
            raise RuntimeError("Missing EMAIL_ADDRESS or EMAIL_PASSWORD in environment.")
        self.email_address = email_address
        self.server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30)
        self.server.ehlo()
        self.server.starttls()
        self.server.ehlo()
        self.server.login(email_address, email_password)

    def close(self):
        if self.server is None:
            return
        try:
            self.server.quit()
        except Exception:
            pass
        finally:
            self.server = None
            self.email_address = None

    def send(self, to_email, subject, body, sender_name="", agency_name=""):
        # Build multipart email with plain text + HTML
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["To"] = to_email

        html_body = build_html_email(subject, body, sender_name, agency_name)
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        attempts = SMTP_MAX_RETRIES + 1
        last_error = None
        for attempt in range(attempts):
            try:
                self.connect()
                if "From" in msg:
                    msg.replace_header("From", f'"{sender_name}" <{self.email_address}>' if sender_name else self.email_address)
                else:
                    msg["From"] = f'"{sender_name}" <{self.email_address}>' if sender_name else self.email_address
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
