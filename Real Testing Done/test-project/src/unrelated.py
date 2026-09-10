"""Shipping service — completely unrelated to the Payment API.

This file uses an 'amount' field, but for a DIFFERENT endpoint (/shipping/rates).
ChangeMesh should NOT flag this as affected by the POST /payments change.

This is an intentional FALSE-POSITIVE CONTROL to test specificity.
"""

import requests

BASE_URL = "http://api.example.com"


def get_shipping_rates(weight_kg: float, destination: str) -> list:
    """Get available shipping rates for a given weight and destination.

    Note: the 'amount' field here refers to package weight,
    sent to /shipping/rates — NOT to /payments.
    """
    payload = {
        "amount": weight_kg,       # <-- 'amount' but for /shipping/rates, NOT /payments
        "destination": destination,
    }
    response = requests.post(f"{BASE_URL}/shipping/rates", json=payload)
    response.raise_for_status()
    return response.json()


def track_package(tracking_id: str) -> dict:
    """Track a package by its tracking ID."""
    response = requests.get(f"{BASE_URL}/shipping/{tracking_id}")
    response.raise_for_status()
    return response.json()


def calculate_shipping_cost(weight_kg: float, destination: str) -> float:
    """Return the cheapest shipping rate."""
    rates = get_shipping_rates(weight_kg, destination)
    return min(r["price"] for r in rates)
