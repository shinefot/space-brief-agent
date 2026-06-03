"""Stage 7b — Delivery via SMTP. Works with Gmail app-passwords, Fastmail,
Resend SMTP, Mailgun SMTP, etc. Sends a multipart text+HTML email."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Settings

log = logging.getLogger("deliver")


def send_email(settings: Settings, subject: str, text_body: str, html_body: str) -> None:
    if not (settings.smtp_host and settings.email_to):
        raise RuntimeError("SMTP host or recipients not configured; cannot send email.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.email_from or settings.smtp_user
    msg["To"] = ", ".join(settings.email_to)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_pass)
        server.sendmail(msg["From"], settings.email_to, msg.as_string())
    log.info("Email sent to %s", ", ".join(settings.email_to))
