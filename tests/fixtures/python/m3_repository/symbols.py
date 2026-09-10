import requests


def decorated() -> None:
    requests.get("/decorated")


class PaymentService:
    def create(self) -> None:
        requests.post("/payments")

    async def fetch(self) -> None:
        requests.get("/payments")


def outer() -> None:
    def inner() -> None:
        requests.get("/nested")

    inner()
