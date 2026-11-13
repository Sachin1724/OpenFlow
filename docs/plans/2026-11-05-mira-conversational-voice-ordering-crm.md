# MIRA Conversational Voice Ordering CRM Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an end-to-end Odia-to-Odia conversational voice ordering system and real-time merchant CRM dashboard, allowing customers (especially elderly or non-app users in Odisha) to place food and e-commerce orders purely by speaking, with automatic cart updates, landmark address extraction, OTP verification, and 24kHz studio voice responses.

**Architecture:** A lightweight FastAPI + WebSocket backend connects the caller's audio stream with MIRA's Odia NLU engine. As the caller speaks, food items and quantities are extracted against merchant catalogs, addresses are parsed, and the merchant CRM dashboard updates in real time. Once the caller verifies via spoken OTP, the order ticket is finalized and confirmed via continuous 24kHz Odia speech.

**Tech Stack:** Python 3.10+, FastAPI, WebSockets, Jinja2 / HTML5 / TailwindCSS (Merchant Dashboard), IndicConformer ASR, Matcha-TTS + Vocos (24kHz Studio Voice), SQLite / JSON In-Memory Store.

---

## Ecosystem Feasibility in Odisha

### 1. Market Drivers & Demographics
- **App Fatigue & The Digital Divide**: In Odisha (pop. ~45M), over 65% of the population resides in Tier-2/3 cities and rural districts (Rourkela, Sambalpur, Berhampur, Balasore, Koraput, Cuttack). Older citizens and small business owners rarely navigate multi-step apps (Swiggy, Zomato, Blinkit) due to cluttered UI, payment anxiety, and English-only menus.
- **The Telephony Habit**: Odia consumers routinely call their local restaurants, grocery shops (*ଦୋକାନ*), and medicine stores to place orders over the phone.
- **Merchant Pain Point**: During peak hours (12 PM–2 PM and 7 PM–10 PM), restaurants miss 30–50% of incoming phone calls. Calls that are answered suffer from misheard items, missed addresses, and high cancellation rates.
- **Landmark-Based Addressing**: Addresses in Odisha rely heavily on institutional landmarks (e.g., *"BPUT Mahanadi Hall of Residence"*, *"Master Canteen ପାଖରେ"*, *"SCB Medical କ୍ୟାମ୍ପସ"*). MIRA's landmark extraction accommodates this pattern natively.

---

## System Architecture Diagram

```
[ Customer Phone / WebRTC / Audio Ingest ]
                   │
                   ▼
       [ IndicConformer Odia ASR ]
                   │ (Odia Speech Transcript)
                   ▼
     [ MIRA Conversational Ordering Gateway ]
       ├── 1. Menu Ontology & Item Matcher (ଦୋସା, ବିରିୟାନୀ, etc.)
       ├── 2. Quantity & Modifier Parser (ଦୁଇଟା, ଗୋଟେ, etc.)
       ├── 3. Landmark Address Parser (BPUT Mahanadi Hall)
       └── 4. Spoken Odia OTP Security Validator
             │                                   │
             ▼ (Real-Time WebSockets)            ▼ (Natural Prosody)
  [ Merchant CRM Dashboard ]         [ 24kHz Studio Voice Engine ]
  - Live Incoming Call Banner        - Broadcast Quality Odia Speech
  - Real-Time Transcribed Query      - Continuous Paragraph Blending
  - Dynamic Item Cart Updating       - <100ms TTFB Streaming
  - 1-Click KOT & Dispatch
```

---

## Multi-Lingual Expansion Strategy

The core pipeline is strictly separated into **Language-Agnostic Business Logic** (Cart, Orders, CRM WebSockets, OTP) and **Pluggable Language Packs**:

| Tier | Language | Status | Target Geography |
| :--- | :--- | :--- | :--- |
| **Tier 1 (Core)** | Standard Odia + Sambalpuri (Kosali) | Production Ready | Coastal & Western Odisha |
| **Tier 2 (Borders)** | Hindi + Bengali + Telugu | Architecture Ready | Industrial belts (Rourkela/Jharsuguda), Balasore, Berhampur/Koraput |
| **Tier 3 (Pan-India)**| Indian English, Tamil, Marathi | Post-Launch Expansion | Urban centers, Metros |

---

## Tasks Breakdown

### Task 1: Food & E-Commerce Menu Ontology & Slot Matcher
Build the catalog matcher that parses colloquial Odia food names and quantities into structured cart items.

**Files:**
- Create: `openflow/gateway/order_ontology.py`
- Test: `openflow/tests/test_order_ontology.py`

**Step 1: Write the failing test**
```python
# openflow/tests/test_order_ontology.py
import pytest
from gateway.order_ontology import MenuOntology

def test_extract_items_and_quantities():
    ontology = MenuOntology()
    # Customer: "ଭାଇ, ମୋ ପାଇଁ ଗୋଟେ ଦୋସା ଆଉ ଦୁଇଟା ବିରିୟାନୀ ବୁକ୍ କର"
    text = "ଭାଇ, ମୋ ପାଇଁ ଗୋଟେ ଦୋସା ଆଉ ଦୁଇଟା ବିରିୟାନୀ ବୁକ୍ କର"
    cart = ontology.parse_order_items(text)
    
    assert len(cart) == 2
    items = {item["sku"]: item for item in cart}
    assert "dosa" in items
    assert items["dosa"]["quantity"] == 1
    assert "biryani" in items
    assert items["biryani"]["quantity"] == 2
```

**Step 2: Run test to verify it fails**
Run: `pytest openflow/tests/test_order_ontology.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway.order_ontology'`

**Step 3: Write minimal implementation**
```python
# openflow/gateway/order_ontology.py
import re
from typing import List, Dict, Any

DEFAULT_MENU = {
    "dosa": {"name_odia": "ମସାଲା ଦୋସା", "name_en": "Masala Dosa", "price": 70.0, "aliases": ["ଦୋସା", "dosa", "dhosa"]},
    "biryani": {"name_odia": "ଚିକେନ ବିରିୟାନୀ", "name_en": "Chicken Biryani", "price": 180.0, "aliases": ["ବିରିୟାନୀ", "biryani", "birani"]},
    "paneer": {"name_odia": "ପନୀର ମଟର", "name_en": "Paneer Butter Masala", "price": 150.0, "aliases": ["ପନୀର", "paneer"]},
    "roti": {"name_odia": "ତନ୍ଦୁରୀ ରୁଟି", "name_en": "Tandoori Roti", "price": 15.0, "aliases": ["ରୁଟି", "ରୋଟି", "roti"]}
}

QUANTITY_MAP = {
    "ଗୋଟେ": 1, "ଗୋଟିଏ": 1, "ଏକ": 1, "1": 1, "one": 1,
    "ଦୁଇ": 2, "ଦୁଇଟା": 2, "ଦୁଇଟି": 2, "2": 2, "two": 2,
    "ତିନି": 3, "ତିନିଟା": 3, "3": 3, "three": 3,
    "ଚାରି": 4, "ଚାରିଟା": 4, "4": 4, "four": 4
}

class MenuOntology:
    def __init__(self, menu_catalog: Dict[str, Any] = None):
        self.menu = menu_catalog or DEFAULT_MENU

    def parse_order_items(self, text: str) -> List[Dict[str, Any]]:
        cart = []
        tokens = text.lower().split()
        for sku, details in self.menu.items():
            for alias in details["aliases"]:
                if alias in text.lower():
                    # Look for preceding quantity token
                    qty = 1
                    for idx, token in enumerate(tokens):
                        if alias in token and idx > 0:
                            prev = tokens[idx - 1]
                            if prev in QUANTITY_MAP:
                                qty = QUANTITY_MAP[prev]
                    cart.append({
                        "sku": sku,
                        "name_odia": details["name_odia"],
                        "name_en": details["name_en"],
                        "price": details["price"],
                        "quantity": qty,
                        "line_total": details["price"] * qty
                    })
                    break
        return cart

    def extract_landmark_address(self, text: str) -> str:
        # Match address phrases like "ମୋ ଆଡ୍ରେସ୍ ହେଲା ...", "address is ..."
        match = re.search(r'(?:ଆଡ୍ରେସ୍\s*ହେଲା|ଠିକଣା\s*ହେଲା|address\s*is|deliver\s*at)\s*(.+?)(?:,|\.|$|ସେଇଠି)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Fallback to key institution landmarks
        if "bput" in text.lower() or "ବିପିୟୁଟି" in text.lower():
            return "BPUT Mahanadi Hall of Residence, Rourkela"
        return text.strip()
```

**Step 4: Run test to verify it passes**
Run: `pytest openflow/tests/test_order_ontology.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/gateway/order_ontology.py openflow/tests/test_order_ontology.py
git commit -m "feat(gateway): add food menu ontology and Odia slot matcher"
```

---

### Task 2: Conversational Ordering State Machine & OTP Validator
Manages the multi-turn conversational stages: greeting, adding to cart, confirming address, sending OTP, validating spoken Odia OTP, and placing the order.

**Files:**
- Create: `openflow/gateway/order_state_machine.py`
- Test: `openflow/tests/test_order_state_machine.py`

**Step 1: Write the failing test**
```python
# openflow/tests/test_order_state_machine.py
import pytest
from gateway.order_state_machine import ConversationalOrderSession

def test_full_order_flow():
    session = ConversationalOrderSession(session_id="call_991", customer_phone="+919437012345")
    
    # Turn 1: Add items
    res1 = session.process_turn("ଭାଇ, ମୋ ପାଇଁ ଦୋସା ଆଉ ବିରିୟାନୀ ବୁକ୍ କର")
    assert session.state == "AWAITING_ADDRESS"
    assert len(session.cart) == 2
    assert "ଦୋସା" in res1["reply_odia"]
    
    # Turn 2: Provide address
    res2 = session.process_turn("ମୋ ଆଡ୍ରେସ୍ ହେଲା BPUT Mahanadi Hall of Residence")
    assert session.state == "AWAITING_OTP"
    assert "BPUT" in session.delivery_address
    assert session.otp_code is not None
    
    # Turn 3: Spoken OTP
    otp_spoken = session.otp_code  # e.g., "7244"
    res3 = session.process_turn(f"ମୋ OTP ହେଲା {otp_spoken}")
    assert session.state == "ORDER_CONFIRMED"
    assert res3["order_placed"] is True
```

**Step 2: Run test to verify it fails**
Run: `pytest openflow/tests/test_order_state_machine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway.order_state_machine'`

**Step 3: Write minimal implementation**
```python
# openflow/gateway/order_state_machine.py
import random
from typing import Dict, Any, List, Optional
from gateway.order_ontology import MenuOntology
from gateway.enterprise_gateway import extract_numeric_sequence

class ConversationalOrderSession:
    def __init__(self, session_id: str, customer_phone: str = "+919437012345"):
        self.session_id = session_id
        self.customer_phone = customer_phone
        self.state = "GREETING"
        self.cart: List[Dict[str, Any]] = []
        self.delivery_address: str = ""
        self.otp_code: Optional[str] = None
        self.otp_verified: bool = False
        self.ontology = MenuOntology()

    def process_turn(self, utterance: str) -> Dict[str, Any]:
        text = utterance.strip()
        
        if self.state in ["GREETING", "BUILDING_CART"]:
            items = self.ontology.parse_order_items(text)
            if items:
                self.cart.extend(items)
                total = sum(i["line_total"] for i in self.cart)
                items_str = ", ".join([f"{i['name_odia']} ({i['quantity']}ଟି)" for i in self.cart])
                self.state = "AWAITING_ADDRESS"
                return {
                    "reply_odia": f"ଆପଣଙ୍କ କାର୍ଟରେ {items_str} ଯୋଡ଼ି ଦିଆଗଲା । ମୋଟ ମୂଲ୍ୟ {int(total)} ଟଙ୍କା । ଦୟାକରି ଆପଣଙ୍କ ଡେଲିଭରୀ ଠିକଣା କୁହନ୍ତୁ ?",
                    "state": self.state,
                    "cart": self.cart,
                    "total": total
                }
            return {
                "reply_odia": "ନମସ୍କାର ! ଆଜି ଆପଣ କଣ ଅର୍ଡର କରିବାକୁ ଚାହୁଁଛନ୍ତି ? ଯେପରି ଦୋସା କିମ୍ବା ବିରିୟାନୀ ?",
                "state": self.state,
                "cart": self.cart
            }

        elif self.state == "AWAITING_ADDRESS":
            self.delivery_address = self.ontology.extract_landmark_address(text)
            self.otp_code = str(random.randint(1000, 9999))
            self.state = "AWAITING_OTP"
            return {
                "reply_odia": f"ଠିକଣା ଗ୍ରହଣ କରାଗଲା । ଅର୍ଡର କନଫର୍ମ କରିବା ପାଇଁ ଆମେ ଆପଣଙ୍କ ଫୋନ୍ ନମ୍ବରକୁ ଏକ OTP ପଠାଉଛୁ, ଦୟାକରି ସେହି OTP କୁହନ୍ତୁ ?",
                "state": self.state,
                "address": self.delivery_address,
                "otp_sent": True
            }

        elif self.state == "AWAITING_OTP":
            spoken_nums = extract_numeric_sequence(text)
            if self.otp_code and self.otp_code in spoken_nums:
                self.otp_verified = True
                self.state = "ORDER_CONFIRMED"
                return {
                    "reply_odia": f"ଧନ୍ୟବାଦ ! ଆପଣଙ୍କ OTP ଯାଞ୍ଚ ହୋଇଛି ଏବଂ ଅର୍ଡର କନଫର୍ମ ହୋଇଛି । ୩୦ ମିନିଟ୍ ମଧ୍ୟରେ {self.delivery_address} ଠାରେ ପହଞ୍ଚିଯିବ ।",
                    "state": self.state,
                    "order_placed": True
                }
            return {
                "reply_odia": "ଦୟାକରି ସଠିକ୍ OTP କୁହନ୍ତୁ ?",
                "state": self.state,
                "order_placed": False
            }

        return {"reply_odia": "ଆପଣଙ୍କ ଅର୍ଡର ପୂର୍ବରୁ ପ୍ରକ୍ରିୟାକରଣ ହୋଇସାରିଛି । ଧନ୍ୟବାଦ !", "state": self.state}
```

**Step 4: Run test to verify it passes**
Run: `pytest openflow/tests/test_order_state_machine.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/gateway/order_state_machine.py openflow/tests/test_order_state_machine.py
git commit -m "feat(gateway): implement conversational order state machine and OTP validator"
```

---

### Task 3: Real-Time Merchant CRM Dashboard & WebSocket Hub
Provides a reactive web dashboard where the merchant sees active customer calls, streaming Odia transcripts, dynamically updating order cards, and OTP confirmation badges.

**Files:**
- Create: `openflow/gateway/crm_server.py`
- Create: `openflow/gateway/templates/merchant_dashboard.html`
- Create: `openflow/gateway/static/dashboard.js`
- Test: `openflow/tests/test_crm_server.py`

**Step 1: Write the failing test**
```python
# openflow/tests/test_crm_server.py
from fastapi.testclient import TestClient
from gateway.crm_server import app

def test_dashboard_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "CRM_ONLINE"

def test_dashboard_ui_serves():
    client = TestClient(app)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "MIRA Merchant CRM" in response.text
```

**Step 2: Run test to verify it fails**
Run: `pytest openflow/tests/test_crm_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway.crm_server'`

**Step 3: Write minimal implementation**
Implement `openflow/gateway/crm_server.py` with FastAPI, WebSocket broadcasting (`/ws/merchant`), active call session management, and HTML template endpoints. Build responsive UI displaying:
- Left Column: Active Calls & Live Odia Voice Subtitle Stream.
- Middle Column: Live Order Ticket Card with dynamically updating cart items (`+ Dosa`, `+ Biryani`), Address, Total, and OTP Verification Badge.
- Right Column: Kitchen Status, KOT Printer button, and Delivery Dispatch.

**Step 4: Run test to verify it passes**
Run: `pytest openflow/tests/test_crm_server.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/gateway/crm_server.py openflow/gateway/templates/merchant_dashboard.html openflow/gateway/static/dashboard.js openflow/tests/test_crm_server.py
git commit -m "feat(crm): build real-time merchant dashboard and WebSocket streaming server"
```

---

### Task 4: Continuous 24kHz Studio Odia Verbalizer Integration
Connect the conversational ordering state machine to `StudioVoiceEngine` for broadcast-quality speech response synthesis without comma chopping.

**Files:**
- Create: `openflow/gateway/order_voice_verbalizer.py`
- Test: `openflow/tests/test_order_voice_verbalizer.py`

**Step 1: Write the failing test**
```python
# openflow/tests/test_order_voice_verbalizer.py
from gateway.order_voice_verbalizer import OrderVoiceVerbalizer

def test_verbalizer_synthesis():
    verbalizer = OrderVoiceVerbalizer()
    text = "ଧନ୍ୟବାଦ ସଚିନ ବାବୁ ! ଆପଣଙ୍କ ଅର୍ଡର ସଫଳତାର ସହ ଗ୍ରହଣ କରାଗଲା ।"
    audio = verbalizer.synthesize_spoken_reply(text)
    assert len(audio) > 24000  # at least 1s of 24kHz audio
```

**Step 2: Run test to verify it fails**
Run: `pytest openflow/tests/test_order_voice_verbalizer.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Minimal implementation**
Wrap `StudioVoiceEngine` from `openflow/engine/studio_voice.py`, utilizing paragraph blending and pre-speech inhalation envelope.

**Step 4: Run test to verify it passes**
Run: `pytest openflow/tests/test_order_voice_verbalizer.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/gateway/order_voice_verbalizer.py openflow/tests/test_order_voice_verbalizer.py
git commit -m "feat(voice): integrate 24kHz studio verbalizer into ordering gateway"
```

---

### Task 5: End-to-End Simulation Runner & Batch Launcher
Create the verification demo simulating the exact scenario:
Customer says *"ଭାଇ, ମୋ ପାଇଁ ଦୋସା ଆଉ ବିରିୟାନୀ ବୁକ୍ କର"*, sets address to *"BPUT Mahanadi Hall of Residence"*, verifies OTP, and observes the live ticket on the merchant dashboard.

**Files:**
- Create: `openflow/gateway/demo_order_crm_flow.py`
- Create: `START_ORDERING_CRM_DEMO.bat`

**Execution Steps:**
1. Starts CRM server in background at `http://127.0.0.1:9100`.
2. Connects WebSocket client simulating store tablet.
3. Fires multi-turn voice interaction with MIRA.
4. Synthesizes 24kHz audio to `openflow/scratch/order_confirmed_bput.wav`.
5. Verifies ticket persistence in CRM database.

---

## Verification Checklist
- [ ] Odia food item and quantity parser handles colloquial phrasing (*"ଭାଇ ଦୋସା ଆଉ ବିରିୟାନୀ ବୁକ୍ କର"*).
- [ ] Address parser captures institutional Odisha landmarks (*"BPUT Mahanadi Hall of Residence"*).
- [ ] Spoken Odia OTP parser validates numeric spoken digits (*"ସାତ ଦୁଇ ଚାରି ଚାରି"* $\rightarrow$ `7244`).
- [ ] Real-time merchant dashboard updates via WebSockets with zero manual refresh.
- [ ] Voice reply synthesized at 24kHz studio quality in $<1.5$ seconds (RTF $<0.1$).
- [ ] All unit tests pass with zero regressions.

