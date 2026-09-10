import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from payment_service import create_payment
from checkout import checkout


def test_payment_functions():
    """Verify payment and checkout functions are callable."""
    assert callable(create_payment)
    assert callable(checkout)


@patch("requests.post")
def test_create_payment_request(mock_post):
    """Verify create_payment sends POST request to /payments."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": 1, "status": "completed"}
    mock_post.return_value = mock_resp

    res = create_payment(amount=49.99, currency="USD")
    mock_post.assert_called_once()
    assert res is not None


@patch("requests.post")
def test_checkout_delegation(mock_post):
    """Verify checkout processes correctly."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": 2, "status": "completed"}
    mock_post.return_value = mock_resp

    res = checkout(cart_total=100.0, currency="EUR")
    mock_post.assert_called_once()
    assert res is not None
