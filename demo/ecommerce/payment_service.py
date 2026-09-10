import requests

BASE_URL = "https://payments.example.com"


def create_payment(price: float, currency: str) -> object:
    return requests.post(
        BASE_URL + "/payments",
        json={"amount": price, "currency": currency},
    )
