try:
    from sample2.src.billing_client import subscribe_customer
except ImportError:
    from billing_client import subscribe_customer


def upgrade_user_tier(user_id: str, tier_name: str) -> dict:
    """Business logic for upgrading an enterprise customer tier."""
    return subscribe_customer(customer_id=user_id, plan_id=tier_name)
