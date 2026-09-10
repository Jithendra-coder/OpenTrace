import requests

BILLING_API_BASE = "https://api.billing.enterprise.io"


def subscribe_customer(customer_id: str, plan_id: str) -> dict:
    """Send subscription creation request to Billing Gateway."""
    response = requests.post(
        BILLING_API_BASE + "/v1/customers/subscriptions",
        json={"customer_id": customer_id, "plan_id": plan_id},
        timeout=10,
    )
    return response.json() if hasattr(response, "json") else {}
