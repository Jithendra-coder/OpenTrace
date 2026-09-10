from demo.ecommerce.checkout import checkout


def place_order(price: float, currency: str) -> object:
    return checkout(price, currency)
