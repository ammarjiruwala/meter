import asyncio
import os
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

PRAVA_LIVE_MODE = os.getenv("PRAVA_LIVE_MODE", "False") == "True"
PRAVA_API_BASE = os.getenv("PRAVA_API_BASE", "https://sandbox.api.prava.space")
PRAVA_API_KEY = os.getenv("PRAVA_API_KEY")
PRAVA_MANDATE_ID = os.getenv("PRAVA_MANDATE_ID")

HEADERS = {
    "Authorization": f"Bearer {PRAVA_API_KEY}",
    "Content-Type": "application/json",
}


async def charge_mandate(amount_usd: float, reference: str):
    """Mint single-use card credentials against the standing mandate. No passkey."""
    amount = f"{amount_usd:.2f}"

    if not PRAVA_LIVE_MODE:
        await asyncio.sleep(1.2)
        return {"status": "awaiting_result", "simulated": True,
                "transactionId": f"sim_{uuid.uuid4().hex[:8]}"}

    url = f"{PRAVA_API_BASE}/v1/mandates/{PRAVA_MANDATE_ID}/charge"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=HEADERS,
                              json={"amount": amount, "reference": reference})
    return r.json()


async def list_mandates():
    """Check remaining headroom. The Treasurer calls this before deciding to charge."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{PRAVA_API_BASE}/v1/mandates", headers=HEADERS)
    return r.json()