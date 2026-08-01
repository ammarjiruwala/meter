import os

import httpx
from dotenv import load_dotenv

load_dotenv()

r = httpx.get(
    "https://sandbox.api.prava.space/v1/mandates",
    headers={"Authorization": f"Bearer {os.getenv('PRAVA_API_KEY')}"},
    timeout=30,
)

for m in r.json()["mandates"]:
    print(
        f"{m['id']}  {m['remaining']}/{m['approvedAmount']} {m['currency']}  "
        f"{m['recurringFrequency']}  {m['status']}"
    )