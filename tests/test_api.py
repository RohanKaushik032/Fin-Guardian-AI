"""Integration tests for the full Fin-Guardian API."""

import pytest
import json
from fastapi.testclient import TestClient
from app.main import app

# ── Test API key (matches the dev key in conftest / .env) ─────────────────
TEST_API_KEY = "dev-key-local-only"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthEndpoints:
    """Test health check endpoints — no auth required."""

    def test_root_endpoint(self, client):
        """Test root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["status"] == "running"

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "degraded"]


class TestTransactionEvaluation:
    """Test transaction evaluation endpoint (requires X-API-Key header)."""

    def test_normal_transaction(self, client):
        """Test evaluating a normal (low-risk) transaction."""
        payload = {
            "account_id": "C_PRIYA_STUDENT_001",
            "recipient_id": "C_LANDLORD_RK_APARTMENTS_002",
            "amount": 10000.0,
            "transaction_type": "TRANSFER",
            "timestamp": "2026-01-15T10:30:00Z",
            "account_age_days": 180,
            "account_balance_before": 50000.0,
            "is_new_recipient": False,
            "sender_tx_count": 10
        }

        response = client.post(
            "/api/v1/transactions/evaluate",
            json=payload,
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

        data = response.json()
        assert "transaction_id" in data
        assert "verdict" in data
        assert "combined_risk_score" in data
        assert "inference_latency_ms" in data

        # Normal transaction should be APPROVE or HOLD
        assert data["verdict"] in ["APPROVE", "HOLD"]
        assert data["combined_risk_score"] < 0.85  # Not deny-level

    def test_suspicious_transaction(self, client):
        """Test evaluating a suspicious (high-risk) transaction."""
        payload = {
            "account_id": "C_PRIYA_STUDENT_001",
            "recipient_id": "C_UNKNOWN_RECIPIENT_999",
            "amount": 92000.0,
            "transaction_type": "TRANSFER",
            "timestamp": "2026-01-15T23:45:00Z",
            "account_age_days": 180,
            "account_balance_before": 95000.0,
            "is_new_recipient": True,
            "sender_tx_count": 3
        }

        response = client.post(
            "/api/v1/transactions/evaluate",
            json=payload,
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

        data = response.json()
        # Suspicious transaction should trigger HOLD or DENY
        assert data["verdict"] in ["HOLD", "DENY"]
        assert data["combined_risk_score"] > 0.5

    def test_response_includes_explanation(self, client):
        """Test that response includes human-readable explanation."""
        payload = {
            "account_id": "C_PRIYA_STUDENT_001",
            "recipient_id": "C_UNKNOWN_RECIPIENT_999",
            "amount": 92000.0,
            "transaction_type": "TRANSFER",
            "timestamp": "2026-01-15T23:45:00Z",
            "account_age_days": 180,
            "account_balance_before": 95000.0,
            "is_new_recipient": True,
            "sender_tx_count": 3
        }

        response = client.post(
            "/api/v1/transactions/evaluate",
            json=payload,
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

        data = response.json()
        assert "shap_top_features" in data
        assert isinstance(data["shap_top_features"], list)

    def test_hold_includes_challenge(self, client):
        """Test that HOLD verdicts include step-up challenge."""
        payload = {
            "account_id": "C_PRIYA_STUDENT_001",
            "recipient_id": "C_UNKNOWN_RECIPIENT_999",
            "amount": 92000.0,
            "transaction_type": "TRANSFER",
            "timestamp": "2026-01-15T23:45:00Z",
            "account_age_days": 180,
            "account_balance_before": 95000.0,
            "is_new_recipient": True,
            "sender_tx_count": 3
        }

        response = client.post(
            "/api/v1/transactions/evaluate",
            json=payload,
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

        data = response.json()
        if data["verdict"] == "HOLD":
            assert "challenge_type" in data
            assert data["challenge_type"] is not None
            assert data["challenge_type"] != "NONE"

    def test_latency_under_30ms(self, client):
        """Test that inference latency is under 30ms."""
        payload = {
            "account_id": "C_PRIYA_STUDENT_001",
            "recipient_id": "C_LANDLORD_RK_APARTMENTS_002",
            "amount": 10000.0,
            "transaction_type": "TRANSFER",
            "timestamp": "2026-01-15T10:30:00Z",
            "account_age_days": 180,
            "account_balance_before": 50000.0,
            "is_new_recipient": False,
            "sender_tx_count": 10
        }

        response = client.post(
            "/api/v1/transactions/evaluate",
            json=payload,
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

        data = response.json()
        assert data["inference_latency_ms"] < 30.0

    def test_missing_required_fields(self, client):
        """Test validation of required fields."""
        incomplete_payload = {
            "account_id": "C_PRIYA_STUDENT_001",
        }

        response = client.post(
            "/api/v1/transactions/evaluate",
            json=incomplete_payload,
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422  # Validation error

    def test_missing_api_key_returns_403(self, client):
        """Test that missing API key returns 403 Forbidden."""
        payload = {
            "account_id": "C_PRIYA_STUDENT_001",
            "recipient_id": "C_UNKNOWN_RECIPIENT_999",
            "amount": 92000.0,
            "transaction_type": "TRANSFER",
            "timestamp": "2026-01-15T23:45:00Z",
            "account_age_days": 180,
            "account_balance_before": 95000.0,
            "is_new_recipient": True,
            "sender_tx_count": 3
        }
        # No AUTH_HEADERS intentionally
        response = client.post("/api/v1/transactions/evaluate", json=payload)
        assert response.status_code == 403

    def test_invalid_api_key_returns_403(self, client):
        """Test that invalid API key returns 403 Forbidden."""
        payload = {
            "account_id": "C_PRIYA_STUDENT_001",
            "recipient_id": "C_UNKNOWN_RECIPIENT_999",
            "amount": 92000.0,
            "transaction_type": "TRANSFER",
            "timestamp": "2026-01-15T23:45:00Z",
            "account_age_days": 180,
            "account_balance_before": 95000.0,
            "is_new_recipient": True,
            "sender_tx_count": 3
        }
        response = client.post(
            "/api/v1/transactions/evaluate",
            json=payload,
            headers={"X-API-Key": "invalid-wrong-key"},
        )
        assert response.status_code == 403


class TestTransactionAPI:
    """Test transaction-specific endpoints."""

    def test_api_status(self, client):
        """Test transaction API status endpoint."""
        response = client.get("/api/v1/transactions/status")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert data["service"] == "transactions-api"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
