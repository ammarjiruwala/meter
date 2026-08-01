import os, uuid, json, httpx
from dotenv import load_dotenv
load_dotenv()

BASE = "https://sandbox.api.prava.space"
MID  = os.getenv("PRAVA_MANDATE_ID")
H    = {"Authorization": f"Bearer {os.getenv('PRAVA_API_KEY')}",
        "Content-Type": "application/json"}

def charge(amount, ref):
    r = httpx.post(f"{BASE}/v1/mandates/{MID}/charge", headers=H,
                   json={"amount": amount, "reference": ref}, timeout=30)
    print(f"\n--- ${amount} ref={ref} -> HTTP {r.status_code}")
    print(json.dumps(r.json(), indent=2))
    return r.json()

# 1. normal charge, should succeed
charge("5.00", f"t1_{uuid.uuid4().hex[:6]}")

# 2. same reference twice -> deduplicated: true
ref = f"t2_{uuid.uuid4().hex[:6]}"
charge("5.00", ref)
charge("5.00", ref)

# 3. over the $50 cap -> THRESHOLD_EXCEEDED
charge("999.00", f"t3_{uuid.uuid4().hex[:6]}")