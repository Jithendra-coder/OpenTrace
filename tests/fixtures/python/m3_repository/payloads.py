import requests

PAYLOAD = {"amount": 10, "customer": {"name": "Ada", "address": {"zip": "1"}}}


def payload_calls(extra: dict[str, object]) -> None:
    requests.post(
        "/payments",
        json={"amount": 10, "customer": {"name": "Ada", "address": {"zip": "1"}}},
        params={"status": "paid", "limit": 10},
        headers={"Authorization": "redacted", "X-Client-ID": "client"},
    )
    requests.post("/payments", json=PAYLOAD)
    requests.post("/payments", json={**extra, "known": 1})
