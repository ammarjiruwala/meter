import uuid

from fastapi import FastAPI

from prava_service import charge_mandate, list_mandates, report_charge

app = FastAPI()


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