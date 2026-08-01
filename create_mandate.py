# create_mandate.py
import os
import httpx
import json
from dotenv import load_dotenv
load_dotenv()

r = httpx.post(
    "https://sandbox.api.prava.space/v1/sessions",
    headers={"Authorization": f"Bearer {os.getenv('PRAVA_API_KEY')}",
             "Content-Type": "application/json"},
    json={
        "user_id": "meter_demo_co",
        "user_email": "shivam@example.com",
        "total_amount": "50.00",
        "currency": "USD",
        "purchase_context": [{
            "merchant_details": {
                "name": "Meter Mock Provider",
                "url": "https://example.com",
                "country_code_iso2": "US"
            },
            "product_details": [{
                "description": "Inference credit top-up",
                "unit_price": "50.00",
                "quantity": 1
            }]
        }],
        "mandate_setup": {
            "intent": "mandate_setup",
            "recurring_frequency": "monthly",
            "merchant_scope": "listed",
            "max_charges": 12
        }
    },
    timeout=30,
)
print(r.status_code)
print(json.dumps(r.json(), indent=2))