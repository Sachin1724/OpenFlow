"""
mock_company_backend.py — Simulated Enterprise Core Banking & CRM Server for Odisha
=================================================================================
Simulates a real Odisha enterprise backend (e.g. Odisha Gramya Bank, Subhadra Portal,
Local E-Commerce store) receiving webhooks from the MIRA Voice Gateway.
"""

import sys
import io
import time
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

# Force UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

app = FastAPI(
    title="Odisha Enterprise Gateway Mock Server",
    description="Enterprise API endpoint receiving structured data from MIRA Voice AI Middleware",
    version="1.0.0"
)

class WebhookPayload(BaseModel):
    session_id: str
    company_id: str
    flow_id: str
    timestamp: float
    customer_data: Dict[str, Any]
    conversation_history: Optional[list] = None

@app.get("/health")
def health_check():
    return {"status": "ONLINE", "server": "Odisha Enterprise Core Banking & CRM Mock", "timestamp": time.time()}

@app.post("/api/kyc/verify")
def verify_kyc(payload: WebhookPayload):
    customer = payload.customer_data
    name = customer.get("customer_name", "ସମ୍ମାନନୀୟ ଗ୍ରାହକ")
    last4 = customer.get("aadhaar_last4", "0000")

    print(f"\n[COMPANY BACKEND] 🏦 Core Banking KYC Webhook Received!")
    print(f"  Session ID   : {payload.session_id}")
    print(f"  Company ID   : {payload.company_id}")
    print(f"  Customer Name: {name}")
    print(f"  Aadhaar Last4: {last4}")

    # Simulate database lookup latency (45ms)
    time.sleep(0.045)

    return {
        "status": "VERIFIED_SUCCESS",
        "code": 200,
        "company": "Odisha Gramya Bank / FinTech",
        "customer_name": name,
        "account_number": "6290-XXXX-4912",
        "kyc_status": "Active & Fully Approved",
        "risk_category": "LOW_RISK",
        "message": "Aadhaar e-KYC record matches UIDAI repository."
    }

@app.post("/api/orders/track")
def track_order(payload: WebhookPayload):
    customer = payload.customer_data
    order_id = customer.get("order_id", "OD-88921")

    print(f"\n[COMPANY BACKEND] 📦 Logistics/E-Commerce Webhook Received!")
    print(f"  Order ID: {order_id}")

    time.sleep(0.035)

    return {
        "status": "OUT_FOR_DELIVERY",
        "order_id": order_id,
        "expected_delivery": "ଆଜି ସନ୍ଧ୍ୟା ୫ଟା ସୁଦ୍ଧା",
        "delivery_partner": "Ekart Express (Bhubaneswar Hub)",
        "destination": "Bhubaneswar, Odisha"
    }

@app.post("/api/schemes/query")
def query_scheme(payload: WebhookPayload):
    customer = payload.customer_data
    name = customer.get("customer_name", "ନାଗରିକ")
    scheme = customer.get("scheme_name", "ସୁଭଦ୍ରା ଯୋଜନା")
    district = customer.get("district", "ଖୋର୍ଦ୍ଧା")

    print(f"\n[COMPANY BACKEND] 🏛️ Civic Scheme Portal Webhook Received!")
    print(f"  Citizen Name : {name}")
    print(f"  Scheme Name  : {scheme}")
    print(f"  District     : {district}")

    time.sleep(0.040)

    return {
        "status": "ELIGIBLE",
        "beneficiary_id": f"OD-{district.upper()}-2024-99128",
        "scheme": scheme,
        "benefit_amount": "₹୧୦,୦୦୦ ପ୍ରତି ବର୍ଷ",
        "installment_date": "ଆସନ୍ତା ଧନତେରସରେ ଜମା ହେବ",
        "assigned_center": f"Mo Seva Kendra, {district}"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="info")

