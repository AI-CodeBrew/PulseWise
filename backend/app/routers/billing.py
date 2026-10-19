"""
Billing for clients: their own plan, usage and invoices, and the entry point for payment-gateway notifications.

Unlike the analytics endpoints, these still work while a client is SUSPENDED: a client locked out for an unpaid
invoice has to be able to see which invoice and how to pay it.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from app.audit import audit
from app.billing import notifications, providers
from app.billing.service import BillingError, record_payment
from app.billing.summary import billing_summary
from app.config import settings
from app.deps import CurrentUser, DbSession, ViewAsClientId, client_ip
from app.models import Client, ClientMember, Invoice

router = APIRouter(prefix="/api", tags=["billing"])


def owner_client(db: DbSession, user: CurrentUser, client_id: uuid.UUID, view_as_client_id: uuid.UUID | None) -> Client:
    """The client, if this user may see its billing: an account OWNER, or an admin. Others get 404 / 403."""
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Not found.")
    if user.is_admin and view_as_client_id is None:
        return client
    if user.is_admin and view_as_client_id == client_id:  # an admin looking "as the client's owner"
        return client
    member = db.get(ClientMember, (client_id, user.id))
    if member is None or member.suspended:
        raise HTTPException(status_code=404, detail="Not found.")  # same answer as "doesn't exist"
    if member.role != "owner":
        raise HTTPException(status_code=403, detail="Only the account owner can see billing.")
    return client


@router.get("/clients/{client_id}/billing", summary="Plan, usage and invoices of a client (account owners only)")
def get_billing(client_id: uuid.UUID, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    return billing_summary(db, owner_client(db, user, client_id, view_as))


@router.post("/clients/{client_id}/invoices/{invoice_id}/checkout", summary="Start an online payment for an open invoice")
async def start_checkout(client_id: uuid.UUID, invoice_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = owner_client(db, user, client_id, view_as)
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.client_id != client.id:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if invoice.status != "open":
        raise HTTPException(status_code=409, detail="This invoice is not waiting for payment.")
    provider = providers.online_provider(db)
    if provider is None:
        raise HTTPException(status_code=409, detail="Online payment isn't available. Please pay as described on this page.")
    try:
        session = await provider.create_checkout(invoice, return_url=f"{settings.frontend_url}/")
    except providers.GatewayError:
        raise HTTPException(status_code=502, detail="The payment service didn't answer. Please try again in a moment, or pay as described on this page.") from None
    if session is None:
        raise HTTPException(status_code=409, detail="Online payment isn't available for this invoice.")
    audit(db, "billing.checkout_started", actor_id=user.id, target_type="invoice", target_id=invoice.id, ip=client_ip(request), details={"provider": provider.name})
    db.commit()
    return {"url": session.url}


@router.get("/clients/{client_id}/invoices/{invoice_id}/pdf", summary="Download an invoice as PDF")
def invoice_pdf(client_id: uuid.UUID, invoice_id: uuid.UUID, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = owner_client(db, user, client_id, view_as)
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.client_id != client.id:  # an invoice id of another client is just "not found"
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return Response(
        content=notifications.render_pdf(db, invoice, client),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice.number}.pdf"'},
    )


@router.post("/billing/webhooks/{provider}", summary="Payment gateway notifications (called by the gateway, not by people)")
async def payment_webhook(provider: str, request: Request, db: DbSession):
    """Public on purpose: gateways can't log in. Security = the gateway's SIGNATURE, checked by the provider class."""
    handler = providers.PROVIDERS.get(provider)
    if handler is None:
        raise HTTPException(status_code=404, detail="Unknown payment provider.")
    try:
        event = handler.parse_webhook(request.headers, await request.body())
    except providers.InvalidWebhook:
        raise HTTPException(status_code=400, detail="Invalid notification.") from None
    if event is None:  # a notification we don't act on
        return {"ok": True, "ignored": True}

    invoice = db.scalar(select(Invoice).where(Invoice.number == event.invoice_number))
    if invoice is None:
        raise HTTPException(status_code=404, detail="Unknown invoice.")
    if event.currency != invoice.currency:
        raise HTTPException(status_code=400, detail="The currency doesn't match the invoice.")
    try:
        payment = record_payment(
            db, invoice, method=event.method, amount=event.amount, reference=event.reference,
            provider=event.provider, provider_payment_id=event.provider_payment_id,
        )
    except BillingError as exc:
        # E.g. the invoice was already paid by bank transfer: tell the gateway "received" so it stops retrying.
        return {"ok": True, "ignored": True, "reason": str(exc)}
    audit(db, "billing.payment_received", target_type="invoice", target_id=invoice.id, ip=client_ip(request),
          details={"provider": event.provider, "amount": str(event.amount), "payment_id": str(payment.id)})
    db.commit()
    return {"ok": True}
