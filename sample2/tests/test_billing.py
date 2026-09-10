import sys
from unittest.mock import MagicMock, patch
from pathlib import Path

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from billing_client import subscribe_customer
from subscription_service import upgrade_user_tier
from billing_controller import handle_plan_change


def test_billing_components_callable():
    assert callable(subscribe_customer)
    assert callable(upgrade_user_tier)
    assert callable(handle_plan_change)


@patch("requests.post")
def test_controller_dispatch_mocked(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"subscription_id": "sub_9921", "status": "active"}
    mock_post.return_value = mock_resp

    payload = {"account_id": "cust_ent_8841", "plan": "enterprise_custom"}
    res = handle_plan_change(payload)
    assert res.get("status") == "active"
    assert mock_post.called
