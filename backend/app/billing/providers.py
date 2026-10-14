"""
Payment providers: the plug where an online payment gateway connects later.

TODAY: payments are manual. The client pays by bank transfer / JazzCash / Easypaisa and you press
"Mark as paid" in the admin panel. That path is the `manual` provider and needs nothing here.

TO ADD A GATEWAY (the plug is ready; no gateway is built in because that needs your merchant account): to accept payments through a gateway (Safepay, PayFast, Paddle, Lemon Squeezy...):
  1. write a class that extends PaymentProvider (below): how to start a checkout, how to verify and read
     the gateway's "payment succeeded" notification (webhook);
  2. register it with `register_provider(MyGateway())`;
  3. point the gateway's webhook at  POST /api/billing/webhooks/<provider name>;
  4. type its name in Admin -> Settings -> "Online payment gateway": clients then get a "Pay online" button on open invoices.
Everything else (recording the payment, closing the invoice, lifting a suspension, audit log) already works,
and is covered by tests that use a pretend gateway.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.models import Invoice


class GatewayError(Exception):
    """The gateway could not be reached or refused to start a payment (log the detail; clients get a plain message)."""


class InvalidWebhook(Exception):
    """The notification is not genuine (bad signature) or not understood."""


@dataclass(frozen=True)
class CheckoutSession:
    url: str  # where to send the client to pay
    provider_reference: str


@dataclass(frozen=True)
class PaymentEvent:
    """A verified "this was paid" notification from a gateway."""

    provider: str
    provider_payment_id: str  # the gateway's own id: used so a repeated notification is recorded once
    invoice_number: str
    amount: Decimal
    currency: str
    method: str = "card"
    reference: str | None = None


class PaymentProvider(ABC):
    name: str

    async def create_checkout(self, invoice: Invoice, *, return_url: str) -> CheckoutSession | None:
        """Start an online payment for an invoice. Return None if this provider has no online checkout."""
        return None

    @abstractmethod
    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> PaymentEvent | None:
        """Verify the gateway's signature and read the notification.

        Return None for notifications we don't care about (e.g. "payment started"). Raise InvalidWebhook
        if the signature is wrong. NEVER trust a webhook without checking its signature.
        """


PROVIDERS: dict[str, PaymentProvider] = {}


def register_provider(provider: PaymentProvider) -> None:
    PROVIDERS[provider.name] = provider


def online_provider(db) -> PaymentProvider | None:
    """The gateway chosen in Admin -> Settings, if it is also registered in the code. None = manual payments only."""
    from app.settings_store import get_setting

    name = str(get_setting(db, "billing.online_provider") or "").strip()
    return PROVIDERS.get(name) if name else None
