from demo.ecommerce.payment_service import create_payment


def checkout(price: float, currency: str) -> object:
    return create_payment(price, currency)
