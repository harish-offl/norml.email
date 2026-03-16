import smtplib
import time
from email.mime.text import MIMEText

from backend.config import (
    SMTP_SERVER,
    SMTP_PORT,
    SMTP_MAX_RETRIES,
    SMTP_RETRY_DELAY_SECONDS,
    get_email_credentials,
)


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

    def send(self, to_email, subject, body):
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["To"] = to_email

        attempts = SMTP_MAX_RETRIES + 1
        last_error = None
        for attempt in range(attempts):
            try:
                self.connect()
                if "From" in msg:
                    msg.replace_header("From", self.email_address)
                else:
                    msg["From"] = self.email_address
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


def send_email(to_email, subject, body):
    """Backward-compatible single send API."""
    with SMTPSender() as sender:
        sender.send(to_email, subject, body)
