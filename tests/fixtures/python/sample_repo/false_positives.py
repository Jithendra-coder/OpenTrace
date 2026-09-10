# ruff: noqa: F401, F811
import requests
from requests import post as imported_post

# requests.post("/comment")
documentation = 'requests.post("/string")'
message = "POST /not-a-call"
my_requests = object()


def post(value: str) -> None:
    return None


def custom() -> None:
    class Requests:
        def post(self, value: str) -> None:
            return None

    requests = Requests()
    requests.post("/shadowed")
    my_requests.post("/lookalike")
    post("/local-function")


def documented() -> None:
    """requests.post('/docstring')"""


def shadowed_parameter(requests: object) -> None:
    requests.post("/parameter-shadow")


def shadowed_from_import() -> None:
    imported_post = object()
    imported_post("/from-shadow")
