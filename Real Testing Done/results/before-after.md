# ChangeMesh Acceptance Test — Before/After Comparison

## 1. API Specification

### Before (v1)
- **File:** `Real Testing Done/test-project/api/openapi-v1.yaml`
- **Operation:** `POST /payments`
- **Request Body Schema:**
```yaml
schema:
  type: object
  required:
    - amount
    - currency
  properties:
    amount:
      type: number
      description: Payment amount
    currency:
      type: string
      description: ISO 4217 currency code
```

### After (v2)
- **File:** `Real Testing Done/test-project/api/openapi-v2.yaml`
- **Operation:** `POST /payments`
- **Request Body Schema:**
```yaml
schema:
  type: object
  required:
    - price
    - currency
  properties:
    price:
      type: number
      description: Payment price (replaces deprecated 'amount' field)
    currency:
      type: string
      description: ISO 4217 currency code
```

---

## 2. Source Code

### `payment_service.py` (Direct Call Site)
**Before:**
```python
def create_payment(amount: float, currency: str = "USD") -> dict:
    payload = {
        "amount": amount,
        "currency": currency,
    }
    response = requests.post(f"{BASE_URL}/payments", json=payload)
    response.raise_for_status()
    return response.json()
```

**After Generated Patch (`changemesh migrate`):**
```python
def create_payment(amount: float, currency: str = "USD") -> dict:
    payload = {
        "currency": currency,
    }
    response = requests.post(f"{BASE_URL}/payments", json=payload)
    response.raise_for_status()
    return response.json()
```

### `payment_client.py` (Indirect Caller)
```python
def process_checkout(cart_total: float, currency: str = "USD") -> str:
    result = create_payment(cart_total, currency)
    return result["id"]
```

### `unrelated.py` (False-Positive Control)
```python
def get_shipping_rates(weight_kg: float, destination: str) -> list:
    payload = {
        "amount": weight_kg,       # <-- 'amount' but for /shipping/rates, NOT /payments
        "destination": destination,
    }
    response = requests.post(f"{BASE_URL}/shipping/rates", json=payload)
    response.raise_for_status()
    return response.json()
```

---

## 3. ChangeMesh Results

| Check | Result | Details |
|---|---|---|
| **API Change Detected** | **PASS** | Detected `request_property_removed: amount` at `request.body[application/json].amount`. |
| **Direct Impact Identified** | **PASS** | `payment_service.py:29` (`payment_service.py::create_payment`) with score `0.80`. |
| **Indirect Impact Traced** | **PASS** | `payment_client.py` (`payment_client.py::process_checkout`, distance: 1) correctly surfaced in CLI & Dashboard. |
| **False-Positive Control (`unrelated.py`)** | **PASS** | Correctly ignored by matcher (score `0.0`). |
| **RouteForge Routing** | **PASS** | Policy `balanced` → `SMALL` strategy (`cli-balanced-decision`). |
| **Deterministic Migration Engine** | **PASS** | Safely routed to `AI_REQUIRED` due to unsupplied host parameter. |
| **AI Migration Engine** | **PASS** | Generated clean patch edit removing `"amount": amount,\n`. |
| **Sandbox Validation** | **PASS** | Ephemeral workspace created, patch applied, Python syntax verified (`Syntax OK: True`). |
| **Git Dry-Run Integration** | **PASS** | Previewed draft PR creation for branch `changemesh/migration-...`. |
| **Working Tree Safety** | **PASS** | Zero uncommitted repository mutations occurred without explicit `changemesh apply`. |
