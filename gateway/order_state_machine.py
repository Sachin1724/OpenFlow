"""
order_state_machine.py — Non-Linear Order State Machine & Surgical Diffs
========================================================================
Enables MIRA CRM to handle mid-sentence modifications, non-linear rollbacks,
and corrections without restarting the ordering workflow.

Examples:
- "Actually, can you change the medium pepperoni to large and add five diet cokes"
- "ନା ଭାଇ, ବିରିୟାନୀ କାଟିଦିଅ, ତା' ବଦଳରେ ଦୁଇଟା ମସାଲା ଦୋସା କରିଦିଅ"
- "ପେପରୋନି ପିଜା ତିନିଟା ବଦଳରେ ଗୋଟେ କରିଦିଅ"
"""

import copy
import re
from typing import Dict, Any, List, Optional, Tuple


MENU_CATALOG: Dict[str, Dict[str, Any]] = {
    "pepperoni_pizza": {
        "name_odia": "ପେପରୋନି ପିଜା",
        "name_en": "Pepperoni Pizza",
        "aliases": ["pepperoni", "pepperoni pizza", "ପେପରୋନି", "ପେପରୋନି ପିଜା", "pizza"],
        "base_price": 280.0,
        "sizes": {"small": 220.0, "medium": 280.0, "large": 380.0},
        "default_size": "medium"
    },
    "veggie_supreme": {
        "name_odia": "ଭେଜ୍ ସୁପ୍ରିମ୍ ପିଜା",
        "name_en": "Veggie Supreme Pizza",
        "aliases": ["veggie supreme", "veggie pizza", "ଭେଜ୍ ପିଜା", "ଭେଜି ସୁପ୍ରିମ", "ଭେଜ୍ ସୁପ୍ରିମ୍", "ଭେଜ୍ ସୁପ୍ରିମ୍ ପିଜା", "ଭେଜି ପିଜା"],
        "base_price": 240.0,
        "sizes": {"small": 190.0, "medium": 240.0, "large": 340.0},
        "default_size": "medium"
    },
    "diet_coke": {
        "name_odia": "ଡାଏଟ୍ କୋକ୍",
        "name_en": "Diet Coke",
        "aliases": ["diet coke", "coke", "diet cokes", "କୋକ୍", "ଡାଏଟ୍ କୋକ୍"],
        "base_price": 40.0,
        "sizes": {"regular": 40.0},
        "default_size": "regular"
    },
    "chicken_biryani": {
        "name_odia": "ଚିକେନ ବିରିୟାନୀ",
        "name_en": "Chicken Biryani",
        "aliases": ["biryani", "chicken biryani", "ବିରିୟାନୀ", "ଚିକେନ ବିରିୟାନୀ"],
        "base_price": 180.0,
        "sizes": {"half": 110.0, "full": 180.0, "family": 340.0},
        "default_size": "full"
    },
    "masala_dosa": {
        "name_odia": "ମସାଲା ଦୋସା",
        "name_en": "Masala Dosa",
        "aliases": ["dosa", "masala dosa", "ଦୋସା", "ମସାଲା ଦୋସା"],
        "base_price": 70.0,
        "sizes": {"regular": 70.0, "special": 95.0},
        "default_size": "regular"
    }
}

QUANTITY_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "ଗୋଟେ": 1, "ଗୋଟିଏ": 1, "ଏକ": 1, "1": 1,
    "ଦୁଇ": 2, "ଦୁଇଟା": 2, "ଦୁଇଟି": 2, "2": 2,
    "ତିନି": 3, "ତିନିଟା": 3, "3": 3,
    "ଚାରି": 4, "ଚାରିଟା": 4, "4": 4,
    "ପାଞ୍ଚ": 5, "ପାଞ୍ଚଟା": 5, "ପାଞ୍ଚଟି": 5, "5": 5,
    "ଛଅ": 6, "ଛଅଟା": 6, "6": 6
}

SIZE_WORDS = {
    "small": "small", "chhota": "small", "ଛୋଟ": "small",
    "medium": "medium", "ମିଡିୟମ୍": "medium", "ମଧ୍ୟମ": "medium",
    "large": "large", "bada": "large", "ବଡ଼": "large", "ଲାର୍ଜ୍": "large",
    "half": "half", "ହାଫ୍": "half",
    "full": "full", "ଫୁଲ୍": "full"
}


class OrderCartItem:
    def __init__(self, sku: str, name_odia: str, name_en: str, quantity: int, size: str, unit_price: float):
        self.sku = sku
        self.name_odia = name_odia
        self.name_en = name_en
        self.quantity = quantity
        self.size = size
        self.unit_price = unit_price

    @property
    def total_price(self) -> float:
        return round(self.quantity * self.unit_price, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku": self.sku,
            "name_odia": self.name_odia,
            "name_en": self.name_en,
            "quantity": self.quantity,
            "size": self.size,
            "unit_price": self.unit_price,
            "total_price": self.total_price
        }


class OrderStateMachine:
    def __init__(self, catalog: Optional[Dict[str, Dict[str, Any]]] = None):
        self.catalog = catalog or MENU_CATALOG
        self.items: Dict[str, OrderCartItem] = {}
        # Event sourcing ledger for rollbacks
        self.history_snapshots: List[Dict[str, Any]] = []

    def _snapshot(self):
        """Saves current state into history snapshot stack."""
        snap = {
            sku: OrderCartItem(
                it.sku, it.name_odia, it.name_en, it.quantity, it.size, it.unit_price
            )
            for sku, it in self.items.items()
        }
        self.history_snapshots.append(snap)

    def rollback(self) -> Tuple[bool, str]:
        """Rolls back to the previous turn's cart state."""
        if not self.history_snapshots:
            return False, "କୌଣସି ପୂର୍ବ ଅର୍ଡର ସ୍ଥିତି ମିଳିଲା ନାହିଁ ।"
        prev = self.history_snapshots.pop()
        self.items = prev
        return True, "ପୂର୍ବ ଅର୍ଡର ସ୍ଥିତିକୁ ଫେରାଇ ଅଣାଗଲା ।"

    def match_sku(self, text: str) -> Optional[str]:
        """Matches spoken phrase against catalog aliases."""
        t_low = text.lower()
        for sku, meta in self.catalog.items():
            for alias in meta["aliases"]:
                if alias in t_low:
                    return sku
        return None

    def process_turn(self, utterance: str) -> Dict[str, Any]:
        """
        Parses customer utterance, generates surgical diffs, updates state,
        and formulates natural Odia & English confirmation speech.
        Supports mid-sentence modifications, non-linear rollbacks, and multi-clause additions.
        """
        u_low = utterance.lower().strip()
        diffs = []

        # 1. Check for explicit rollback / undo triggers
        if any(w in u_low for w in ["undo", "rollback", "ପୂର୍ବ ଅର୍ଡର", "ଆଗ ଭଳି"]):
            success, msg = self.rollback()
            return {
                "action": "rollback",
                "diffs": [{"action": "rollback"}],
                "cart": self.get_cart_summary(),
                "response_odia": msg,
                "response_en": "I've rolled back your order to the previous state."
            }

        self._snapshot()

        # 2. Decompose multi-intent utterance into logical grammatical clauses
        clauses = [
            c.strip()
            for c in re.split(
                r'[,;]|\s+(?:and\s+also|and\s+add|and|also|plus|ଆଉ|ଏବଂ|ତଥା)\s+',
                utterance,
                flags=re.IGNORECASE
            )
            if c.strip()
        ]

        for clause in clauses:
            c_low = clause.lower()

            # A. Check modification / size change (e.g. "change pepperoni to large", "ପେପରୋନି ବଡ଼ କରିଦିଅ")
            mod_m = re.search(
                r'(?:change|make|modify|କର|କରିଦିଅ|ବଦଳାଅ)\s+(?:the\s+)?([a-zA-Z\u0B00-\u0B7F\s]+?)\s+(?:to|in|ରେ)\s+(\w+)',
                clause,
                re.IGNORECASE
            )
            if mod_m:
                it_phr = mod_m.group(1).strip().lower()
                new_sz_w = mod_m.group(2).strip().lower()
                sku = self.match_sku(it_phr)
                if sku and sku in self.items and new_sz_w in SIZE_WORDS:
                    new_sz = SIZE_WORDS[new_sz_w]
                    old_sz = self.items[sku].size
                    self.items[sku].size = new_sz
                    new_p = self.catalog[sku]["sizes"].get(new_sz, self.items[sku].unit_price)
                    self.items[sku].unit_price = new_p
                    diffs.append({
                        "action": "modify",
                        "target": sku,
                        "field": "size",
                        "old_value": old_sz,
                        "new_value": new_sz,
                        "new_price": new_p
                    })
                    continue

            # B. Check removal (e.g. "remove biryani", "ବିରିୟାନୀ କାଟିଦିଅ")
            rem_m = (
                re.search(r'(?:remove|cancel|drop|delete|କାଟିଦିଅ|ହଟାଅ|ବାଦ୍)\s+(?:the\s+)?([a-zA-Z\u0B00-\u0B7F\s]+)', clause, re.IGNORECASE)
                or re.search(r'([a-zA-Z\u0B00-\u0B7F\s]+?)\s+(?:କାଟିଦିଅ|ହଟାଇଦିଅ|ଦରକାର\s+ନାହିଁ)', clause, re.IGNORECASE)
            )
            if rem_m:
                it_phr = rem_m.group(1).strip().lower()
                sku = self.match_sku(it_phr)
                if sku and sku in self.items:
                    rem_it = self.items.pop(sku)
                    diffs.append({"action": "remove", "target": sku, "qty": rem_it.quantity})
                    continue

            # C. Check replacement (e.g. "ବିରିୟାନୀ ବଦଳରେ ଦୁଇଟା ଦୋସା")
            repl_m = re.search(
                r'([a-zA-Z\u0B00-\u0B7F\s]+?)\s+(?:instead\s+of|badalre|ବଦଳରେ)\s+([a-zA-Z\u0B00-\u0B7F\s]+)',
                clause,
                re.IGNORECASE
            )
            if repl_m:
                new_part = repl_m.group(1).strip()
                old_part = repl_m.group(2).strip()
                old_sku = self.match_sku(old_part)
                new_sku = self.match_sku(new_part)
                if old_sku and old_sku in self.items:
                    rem_it = self.items.pop(old_sku)
                    diffs.append({"action": "remove", "target": old_sku, "qty": rem_it.quantity})
                if new_sku:
                    qty = self._extract_quantity(new_part) or 1
                    meta = self.catalog[new_sku]
                    size = meta["default_size"]
                    price = meta["sizes"].get(size, meta["base_price"])
                    self.items[new_sku] = OrderCartItem(new_sku, meta["name_odia"], meta["name_en"], qty, size, price)
                    diffs.append({"action": "add", "target": new_sku, "qty": qty, "size": size})
                continue

            # D. Item addition / placement (e.g. "five diet cokes", "ଗୋଟେ ବିରିୟାନୀ")
            sku = self.match_sku(clause)
            if sku:
                qty = self._extract_quantity(clause) or 1
                meta = self.catalog[sku]
                size = meta["default_size"]
                for sz_w, sz_val in SIZE_WORDS.items():
                    if sz_w in c_low:
                        size = sz_val
                        break
                price = meta["sizes"].get(size, meta["base_price"])
                if sku in self.items:
                    # Increment if not already modified in this turn
                    if not any(d.get("target") == sku for d in diffs):
                        self.items[sku].quantity += qty
                        diffs.append({"action": "increment", "target": sku, "qty_delta": qty})
                else:
                    self.items[sku] = OrderCartItem(sku, meta["name_odia"], meta["name_en"], qty, size, price)
                    diffs.append({"action": "add", "target": sku, "qty": qty, "size": size})

        # 3. Formulate natural spoken Odia & English confirmations
        resp_odia = self._formulate_diff_response_odia(diffs)
        resp_en = self._formulate_diff_response_en(diffs)

        return {
            "diffs": diffs,
            "cart": self.get_cart_summary(),
            "response_odia": resp_odia,
            "response_en": resp_en
        }

    # Alias for process_turn
    process_utterance = process_turn

    def _extract_quantity(self, text: str) -> Optional[int]:
        tokens = text.lower().split()
        for tok in tokens:
            if tok in QUANTITY_WORDS:
                return QUANTITY_WORDS[tok]
            if tok.isdigit():
                return int(tok)
        return None

    def _formulate_diff_response_odia(self, diffs: List[Dict[str, Any]]) -> str:
        if not diffs:
            return "ଆପଣଙ୍କ କାର୍ଟରେ କୌଣସି ପରିବର୍ତ୍ତନ ହୋଇନାହିଁ । ଆପଣ ଆଉ କ'ଣ ଚାହାଁନ୍ତି ?"

        phrases = []
        for d in diffs:
            t = d.get("target", "")
            meta = self.catalog.get(t, {})
            name_odia = meta.get("name_odia", t)

            if d["action"] == "modify" and d.get("field") == "size":
                new_sz = d['new_value'].capitalize()
                phrases.append(f"{name_odia}କୁ {new_sz} ସାଇଜ୍ କରିଦେଲି")
            elif d["action"] == "add":
                phrases.append(f"{d['qty']}ଟି {name_odia} ଯୋଡ଼ିଦେଲି")
            elif d["action"] == "increment":
                phrases.append(f"ଆଉ {d['qty_delta']}ଟି {name_odia} ବଢ଼ାଇଦେଲି")
            elif d["action"] == "remove":
                phrases.append(f"{name_odia} ହଟାଇଦେଲି")

        joined = " ଏବଂ ".join(phrases)
        total = self.get_cart_summary()["grand_total"]
        return f"ଆଜ୍ଞା, {joined} । ସମୁଦାୟ ମୂଲ୍ୟ ହେଲା {int(total)} ଟଙ୍କା ।"

    def _formulate_diff_response_en(self, diffs: List[Dict[str, Any]]) -> str:
        if not diffs:
            return "No changes made to your cart. What else would you like?"

        phrases = []
        for d in diffs:
            t = d.get("target", "")
            meta = self.catalog.get(t, {})
            name_en = meta.get("name_en", t)

            if d["action"] == "modify" and d.get("field") == "size":
                new_sz = d['new_value'].capitalize()
                phrases.append(f"changed {name_en} to {new_sz}")
            elif d["action"] == "add":
                phrases.append(f"added {d['qty']} {name_en}")
            elif d["action"] == "increment":
                phrases.append(f"added {d['qty_delta']} more {name_en}")
            elif d["action"] == "remove":
                phrases.append(f"removed {name_en}")

        joined = ", and ".join(phrases)
        total = self.get_cart_summary()["grand_total"]
        return f"Sure! I've {joined}. Your total is ₹{int(total)}."

    _formulate_diff_response = _formulate_diff_response_odia

    def get_cart_summary(self) -> Dict[str, Any]:
        items_list = [it.to_dict() for it in self.items.values()]
        grand_total = round(sum(it.total_price for it in self.items.values()), 2)
        total_items = sum(it.quantity for it in self.items.values())
        return {
            "items": items_list,
            "item_count": len(items_list),
            "total_items": total_items,
            "total_quantity": total_items,
            "grand_total": grand_total,
            "total_price": grand_total,
            "history_version": len(self.history_snapshots)
        }