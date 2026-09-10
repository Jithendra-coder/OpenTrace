try:
    from sample2.src.subscription_service import upgrade_user_tier
except ImportError:
    from subscription_service import upgrade_user_tier


def handle_plan_change(request_payload: dict) -> dict:
    """Controller route handler for enterprise tier changes."""
    cust_id = request_payload.get("account_id", "")
    target_plan = request_payload.get("plan", "pro")
    return upgrade_user_tier(user_id=cust_id, tier_name=target_plan)
