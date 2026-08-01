"""Mock provider billing — stands in for OpenAI's billing system.

CONTEXT.md §3 is explicit that this is the one thing we simulate: a Prava sandbox card
cannot actually top up a real OpenAI account, so this endpoint plays the provider. It
accepts the single-use credentials minted by a mandate charge and credits the wallet.

Everything on the Prava side of this line is real — real mandate, real network token,
real refusal when the charge is over cap. Only the merchant accepting the card is ours.
Say that out loud in the demo; a judge who spots it unaided will assume more is faked
than actually is.

Owner: Shivam (Payments & Agent).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import db

router = APIRouter(prefix="/mock-openai", tags=["mock-provider"])


class BillingRequest(BaseModel):
    """What a real provider's billing form would collect."""

    token: str = Field(..., description="Visa network token from the mandate charge")
    dynamic_cvv: str = Field(..., description="Single-use CVV — changes every charge")
    expiry_month: str | None = None
    expiry_year: str | None = None
    amount_usd: float = Field(..., gt=0)
    project_id: str = "demo-project"
    provider: str = "openai"


class BillingResponse(BaseModel):
    accepted: bool
    receipt_id: str | None = None
    balance_usd: float | None = None
    decline_reason: str | None = None


@router.post("/billing", response_model=BillingResponse)
def billing(req: BillingRequest) -> BillingResponse:
    """Charge the card and credit the provider balance.

    The validation below is deliberately shallow — it checks the credential is shaped
    like a card, not that it is a real one. A mock that declines a valid Prava token
    would break the demo; a mock that accepts an empty string would prove nothing.
    """
    digits = "".join(c for c in req.token if c.isdigit())
    if len(digits) < 12:
        return BillingResponse(accepted=False, decline_reason="INVALID_CARD_NUMBER")
    if not (req.dynamic_cvv or "").strip():
        return BillingResponse(accepted=False, decline_reason="MISSING_CVV")

    wallet_id = db.ensure_wallet(req.project_id, req.provider)
    balance = db.adjust_balance(wallet_id, req.amount_usd)

    return BillingResponse(
        accepted=True,
        receipt_id=f"rcpt_{uuid.uuid4().hex[:10]}",
        balance_usd=balance,
    )
