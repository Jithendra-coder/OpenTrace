import requests


def response_fields() -> str:
    response = requests.get("/users/42")
    payload = response.json()
    name = payload["name"]
    return name


def nested_response() -> object:
    response = requests.get("/users/42")
    return response.json()["customer"]["phone"]


def metadata_is_not_payload() -> int:
    response = requests.get("/users/42")
    return response.status_code
