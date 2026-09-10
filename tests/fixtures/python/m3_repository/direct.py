import httpx as hx
import requests
import requests as r
from requests import post as send_post


def direct_calls() -> None:
    requests.get("/get")
    r.post("/post")
    send_post("/from-import")
    hx.put("https://payments.example.com/put")


client = hx.Client()
session = r.Session()
client.delete("/delete")
session.patch("/session")


async def async_calls() -> None:
    async with hx.AsyncClient() as async_client:
        await async_client.post("/async")
