"""
Sending email: password-reset and invitation links, invoices, alerts, weekly reports.

Without SMTP settings in .env, emails are NOT sent. They are printed to the backend
console instead, which is handy in development: copy the link from there.
In production, set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD and SMTP_FROM
(any email provider works, e.g. Brevo, Resend, Amazon SES, Gmail with an app password).
"""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger(__name__)

# (file name, content, MIME type), e.g. ("invoice.pdf", b"...", "application/pdf")
Attachment = tuple[str, bytes, str]


def email_configured() -> bool:
    return bool(settings.smtp_host)


def send_email(to: str, subject: str, body: str, *, html: str | None = None, attachments: list[Attachment] | None = None) -> bool:
    """Send an email (plain text, with an optional HTML version and attachments).

    Returns True if it was handed to the mail server, False if email isn't configured or sending failed.
    Never raises: a mail problem must not break whatever triggered the email.
    """
    if not email_configured():
        names = ", ".join(a[0] for a in attachments or [])
        log.warning(
            "EMAIL NOT SENT (SMTP_HOST not set). It would have gone to %s\nSubject: %s\n%s%s",
            to, subject, body, f"\n[attachments: {names}]" if names else "",
        )
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    for filename, content, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        message.add_attachment(content, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)

    try:
        # Port 465 = SSL from the start; other ports (587) upgrade with STARTTLS.
        if settings.smtp_port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with server:
            if settings.smtp_port != 465 and settings.smtp_starttls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        # Never crash a request because email failed; we just log it.
        log.exception("Could not send email to %s (subject: %s)", to, subject)
        return False
