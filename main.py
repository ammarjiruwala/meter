import uuid

from fastapi import FastAPI

from prava_service import charge_mandate, list_mandates, report_charge
from treasury import db as treasury_db
from treasury.mock_provider import router as mock_provider_router

app = FastAPI()
app.include_router(mock_provider_router)


@app.get("/")
def read_root():
    return {"status": "Meter Proxy is running"}


@app.get("/mandates")
async def mandates():
    data = await list_mandates()
    return [
        {
            "id": m["id"],
            "remaining": m["remaining"],
            "approved": m["approvedAmount"],
            "frequency": m["recurringFrequency"],
            "status": m["status"],
        }
        for m in data["mandates"]
    ]


@app.get("/wallets")
def wallets():
    """Provider balances. Backs the dashboard's Provider Balances card."""
    return treasury_db.list_wallets()


@app.post("/wallets/seed")
def seed_wallet(project_id: str = "demo-project", provider: str = "openai",
                balance_usd: float = 4.00):
    """Create a wallet at a starting balance. $4 is the demo's 'too low' state.

    Idempotent: the balance applies on creation only, so re-running this never wipes a
    top-up the Treasurer already made.
    """
    wallet_id = treasury_db.ensure_wallet(project_id, provider, balance_usd)
    return treasury_db.get_wallet(wallet_id)


@app.post("/charge")
async def charge(amount: float = 2.00):
    return await charge_mandate(amount, f"api_{uuid.uuid4().hex[:8]}")


@app.post("/report")
async def report(transaction_id: str, approved: bool = True):
    """Settle a charge. `transactionId` comes from the /charge response."""
    return await report_charge(transaction_id, approved)


@app.post("/charge-refusal")
async def charge_refusal():
    """Over the cap. Visa declines. This is the demo beat."""
    return await charge_mandate(999.00, f"refuse_{uuid.uuid4().hex[:8]}")