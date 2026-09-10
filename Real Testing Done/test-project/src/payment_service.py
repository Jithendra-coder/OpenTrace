"""Payment service — sends payment requests to the external Payment API.

This module is the ONLY file that should be flagged as affected
when the 'amount' request property is removed from POST /payments.
"""

import requests

BASE_URL = "http://api.example.com"


def create_payment(amount: float, currency: str = "USD") -> dict:
    """Create a new payment via the Payment API.

    Args:
        amount: The payment amount in the given currency.
        currency: ISO 4217 currency code (default: USD).

    Returns:
        Response dict containing 'id' and 'status'.

    Raises:
        requests.HTTPError: If the API returns a non-2xx response.
    """
    payload = {
        "amount": amount,
        "currency": currency,
    }
    response = requests.post(f"{BASE_URL}/payments", json=payload)
    response.raise_for_status()
    return response.json()


def refund_payment(payment_id: str) -> dict:
    """Refund an existing payment by ID.

    Args:
        payment_id: The ID returned by create_payment.

    Returns:
        Response dict containing 'status'.
    """
    response = requests.post(
        f"{BASE_URL}/payments/{payment_id}/refunds"
    )
    response.raise_for_status()
    return response.json()


def get_payment_status(payment_id: str) -> str:
    """Return the current status string of a payment."""
    response = requests.get(f"{BASE_URL}/payments/{payment_id}")
    response.raise_for_status()
    return response.json()["status"]
