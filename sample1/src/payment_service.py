import requests

BASE_URL = "https://payments.example.com"


def create_payment(amount: float, currency: str) -> object:
    """Create a payment transaction via the Payment API."""
    return requests.post(
        BASE_URL + "/payments",
        json={"amount": amount, "currency": currency},
    )
