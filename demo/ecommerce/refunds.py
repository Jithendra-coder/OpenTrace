import requests


def create_refund(amount: float) -> object:
    return requests.post(
        "https://refunds.example.com/refunds",
        json={"amount": amount},
    )
