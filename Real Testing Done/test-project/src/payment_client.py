"""High-level payment client used by the checkout flow.

This module calls create_payment from payment_service.
It should appear as an INDIRECT (blast-radius) impact,
not a direct impact, because it does not itself call the API.
"""

from payment_service import create_payment, refund_payment


def process_checkout(cart_total: float, currency: str = "USD") -> str:
    """Process a checkout payment and return the payment ID.

    Args:
        cart_total: Total cart value.
        currency: ISO 4217 currency code.

    Returns:
        The payment ID from the payment API.
    """
    result = create_payment(cart_total, currency)
    return result["id"]


def handle_refund(payment_id: str) -> bool:
    """Attempt to refund a payment.

    Returns:
        True if the refund was processed successfully.
    """
    result = refund_payment(payment_id)
    return result.get("status") == "refunded"
