"""Emails about invoices: the invoice itself, "it's due", "it's overdue". Also builds the invoice PDF."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import emailer
from app.billing import pdf
from app.billing.service import balance, paid_amount
from app.config import settings
from app.models import Client, ClientMember, Invoice, User
from app.settings_store import get_setting

log = logging.getLogger(__name__)


def business_name(db: Session) -> str:
    return get_setting(db, "billing.business_name") or settings.brand_name


def render_pdf(db: Session, invoice: Invoice, client: Client) -> bytes:
    return pdf.invoice_pdf(
        invoice, client,
        business_name=business_name(db),
        business_address=get_setting(db, "billing.business_address"),
        payment_instructions=get_setting(db, "billing.payment_instructions"),
        footer=get_setting(db, "billing.invoice_footer"),
        paid_total=Decimal(str(paid_amount(invoice))),
    )


def recipients(db: Session, client: Client) -> list[str]:
    """Who gets the client's billing emails: the contact email plus the people who own the account."""
    emails = [client.contact_email] if client.contact_email else []
    emails += db.scalars(
        select(User.email).join(ClientMember, ClientMember.user_id == User.id)
        .where(ClientMember.client_id == client.id, ClientMember.role == "owner", ClientMember.suspended.is_(False), User.is_active.is_(True))
    ).all()
    return list(dict.fromkeys(e for e in emails if e))


def _send(db: Session, invoice: Invoice, client: Client, subject: str, text: str) -> bool:
    if not emailer.email_configured():
        return False
    to = recipients(db, client)
    if not to:
        return False
    attachment = (f"{invoice.number}.pdf", render_pdf(db, invoice, client), "application/pdf")
    sent = [emailer.send_email(address, subject, text, attachments=[attachment]) for address in to]
    return any(sent)


def _how_to_pay(db: Session) -> str:
    instructions = get_setting(db, "billing.payment_instructions")
    return f"\nHow to pay:\n{instructions}\n" if instructions else ""


def send_invoice_email(db: Session, invoice: Invoice, client: Client) -> bool:
    """Email a new invoice (with the PDF). Marks `emailed_at` only if it really went out. Commits."""
    name = business_name(db)
    ok = _send(
        db, invoice, client,
        f"Invoice {invoice.number} from {name}",
        f"Hello {client.name},\n\nYour invoice {invoice.number} for {invoice.currency} {invoice.amount} is attached.\n"
        f"It is due on {invoice.due_date:%d %b %Y}.\n{_how_to_pay(db)}\nThank you,\n{name}\n",
    )
    if ok:
        invoice.emailed_at = datetime.now(timezone.utc)
        db.commit()
    return ok


def send_due_reminder(db: Session, invoice: Invoice, client: Client) -> bool:
    name = business_name(db)
    ok = _send(
        db, invoice, client,
        f"Reminder: invoice {invoice.number} is due {'today' if invoice.due_date <= datetime.now(timezone.utc).date() else 'tomorrow'}",
        f"Hello {client.name},\n\nA friendly reminder that invoice {invoice.number} ({invoice.currency} {balance(invoice)}) is due on {invoice.due_date:%d %b %Y}.\n"
        f"{_how_to_pay(db)}\nIf you have already paid, thank you, and please ignore this message.\n\n{name}\n",
    )
    if ok:
        invoice.reminder_sent_at = datetime.now(timezone.utc)
        db.commit()
    return ok


def send_overdue_notice(db: Session, invoice: Invoice, client: Client) -> bool:
    name = business_name(db)
    grace = get_setting(db, "billing.grace_days")
    ok = _send(
        db, invoice, client,
        f"Invoice {invoice.number} is overdue",
        f"Hello {client.name},\n\nInvoice {invoice.number} ({invoice.currency} {balance(invoice)}) was due on {invoice.due_date:%d %b %Y} and is still unpaid.\n"
        f"To keep your dashboard running, please pay within {grace} days of the due date.\n{_how_to_pay(db)}\n"
        f"If you have already paid, please reply with the payment reference.\n\n{name}\n",
    )
    if ok:
        invoice.overdue_notice_sent_at = datetime.now(timezone.utc)
        db.commit()
    return ok
