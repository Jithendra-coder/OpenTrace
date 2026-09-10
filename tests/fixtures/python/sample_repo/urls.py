import requests

BASE_URL = "https://payments.example.com"


def resolved(order_id: str) -> None:
    local = BASE_URL + "/orders"
    requests.get(local + "?status=pending")
    requests.get(f"{BASE_URL}/orders/{order_id}")


def unresolved(order: object) -> None:
    requests.post(build_url(order))


def build_url(order: object) -> str:
    return str(order)


def other_host() -> None:
    requests.get("https://identity.example.com/orders")
