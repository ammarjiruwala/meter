import os, uuid, json, httpx
from dotenv import load_dotenv
load_dotenv()

MID = "mdt_01KYXXC3E0KXSCNNAHZ6DWMW05"   # the one_time mandate
H = {"Authorization": f"Bearer {os.getenv('PRAVA_API_KEY')}",
     "Content-Type": "application/json"}

def charge(amount, ref):
    r = httpx.post(f"https://sandbox.api.prava.space/v1/mandates/{MID}/charge",
                   headers=H, json={"amount": amount, "reference": ref}, timeout=30)
    d = r.json()
    print(f"\n--- ${amount} ref={ref} -> HTTP {r.status_code}")
    print(f"    status: {d.get('status')}  err: {d.get('errorMessage', '-')[:90]}")
    return d

charge("2.00", f"a_{uuid.uuid4().hex[:6]}")   # 1st
charge("2.00", f"b_{uuid.uuid4().hex[:6]}")   # 2nd — can we charge twice?
charge("999.00", f"c_{uuid.uuid4().hex[:6]}") # over cap — THRESHOLD_EXCEEDED?