from payment_service import create_payment


def checkout(cart_total: float, currency: str) -> object:
    """Process checkout by calling the payment service."""
    return create_payment(amount=cart_total, currency=currency)
