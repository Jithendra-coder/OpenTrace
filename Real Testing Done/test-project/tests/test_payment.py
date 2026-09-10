"""Tests for the payment service.

These tests verify the CURRENT (v1 API) behavior.
After migration, tests referencing 'amount' will need to be updated —
this is expected and is part of the migration evidence.
"""

from unittest.mock import MagicMock, call, patch

import pytest


def test_create_payment_sends_amount_and_currency():
    """Verify create_payment sends 'amount' and 'currency' in the payload."""
    from payment_service import create_payment

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "pay_abc123", "status": "success"}

    with patch("payment_service.requests.post", return_value=mock_response) as mock_post:
        result = create_payment(100.0, "USD")

    args, kwargs = mock_post.call_args
    payload = kwargs.get("json", {})
    assert payload["amount"] == 100.0, "Expected 'amount' field in request payload"
    assert payload["currency"] == "USD", "Expected 'currency' field in request payload"
    assert result["id"] == "pay_abc123"


def test_create_payment_default_currency_is_usd():
    """Verify default currency is USD."""
    from payment_service import create_payment

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "pay_def456", "status": "success"}

    with patch("payment_service.requests.post", return_value=mock_response) as mock_post:
        create_payment(50.0)

    args, kwargs = mock_post.call_args
    payload = kwargs.get("json", {})
    assert payload["currency"] == "USD"


def test_create_payment_calls_correct_endpoint():
    """Verify create_payment posts to /payments."""
    from payment_service import create_payment

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "pay_789", "status": "success"}

    with patch("payment_service.requests.post", return_value=mock_response) as mock_post:
        create_payment(25.0, "EUR")

    url = mock_post.call_args.args[0]
    assert "/payments" in url
    assert "/refunds" not in url


def test_refund_payment_calls_refund_endpoint():
    """Verify refund_payment posts to /payments/{id}/refunds."""
    from payment_service import refund_payment

    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "refunded"}

    with patch("payment_service.requests.post", return_value=mock_response) as mock_post:
        result = refund_payment("pay_abc123")

    url = mock_post.call_args.args[0]
    assert "pay_abc123" in url
    assert "refunds" in url
    assert result["status"] == "refunded"


def test_process_checkout_returns_payment_id():
    """Verify process_checkout returns the payment ID."""
    from payment_client import process_checkout

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "pay_checkout_001", "status": "success"}

    with patch("payment_service.requests.post", return_value=mock_response):
        payment_id = process_checkout(199.99, "USD")

    assert payment_id == "pay_checkout_001"
