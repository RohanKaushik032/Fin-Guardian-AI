"""Unit tests for the fraud detection models and inference logic."""

import pytest
from datetime import datetime, timezone
from app.schemas.transaction import IncomingTransaction, TransactionType, RiskVerdict
from app.inference import registry, run_inference, should_fast_approve

@pytest.fixture(scope="session", autouse=True)
def setup_models():
    """Load model registry once for the entire test session."""
    if not registry.is_loaded:
        registry.load_all(artifacts_dir="artifacts")


@pytest.fixture
def sample_transaction():
    """Create a sample transaction for testing."""
    return IncomingTransaction(
        account_id="C_PRIYA_STUDENT_001",
        recipient_id="C_LANDLORD_RK_APARTMENTS_002",
        amount=10000.0,
        transaction_type=TransactionType.TRANSFER,
        timestamp=datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        account_age_days=180,
        account_balance_before=50000.0,
        is_new_recipient=False,
        sender_tx_count=10
    )


@pytest.fixture
def suspicious_transaction():
    """Create a suspicious transaction for testing."""
    return IncomingTransaction(
        account_id="C_PRIYA_STUDENT_001",
        recipient_id="C_UNKNOWN_RECIPIENT_999",
        amount=92000.0,
        transaction_type=TransactionType.TRANSFER,
        timestamp=datetime(2026, 1, 15, 23, 45, 0, tzinfo=timezone.utc),
        account_age_days=180,
        account_balance_before=95000.0,
        is_new_recipient=True,
        sender_tx_count=3
    )


class TestFraudDetector:
    """Test suite for inference registry and execution."""
    
    def test_initialization(self):
        """Test that the model registry is loaded correctly."""
        assert registry.is_loaded is True
    
    def test_predict_normal_transaction(self, sample_transaction):
        """Test fraud score and verdict for a normal transaction."""
        result = run_inference(sample_transaction)
        assert result.combined_risk_score is not None
        assert 0 <= result.combined_risk_score <= 1
        assert result.combined_risk_score < 0.5  # Should be low risk
        assert result.verdict in [RiskVerdict.APPROVE, RiskVerdict.HOLD]
    
    def test_predict_suspicious_transaction(self, suspicious_transaction):
        """Test fraud score and verdict for a suspicious transaction."""
        result = run_inference(suspicious_transaction)
        assert result.combined_risk_score is not None
        assert 0 <= result.combined_risk_score <= 1
        assert result.combined_risk_score > 0.5  # Should be high risk
        assert result.verdict in [RiskVerdict.HOLD, RiskVerdict.DENY]
    
    def test_fraud_score_components(self, suspicious_transaction):
        """Test that all expected components are returned in the result."""
        result = run_inference(suspicious_transaction)
        assert result.xgb_fraud_prob is not None
        assert result.autoencoder_recon_error is not None
        assert result.shap_top_features is not None
        assert result.inference_latency_ms is not None
    
    def test_hour_encoding(self):
        """Test that hour encoding behaves correctly for close times."""
        # Hour 23 (11 PM) and hour 0 (midnight) should have similar scores
        tx_23 = IncomingTransaction(
            account_id="TEST001_SENDER",
            recipient_id="TEST002_RECIPIENT",
            amount=1000.0,
            transaction_type=TransactionType.TRANSFER,
            timestamp=datetime(2026, 1, 15, 23, 0, 0, tzinfo=timezone.utc),
            account_age_days=100,
            account_balance_before=10000.0,
            is_new_recipient=False,
            sender_tx_count=5
        )
        
        tx_0 = IncomingTransaction(
            account_id="TEST001_SENDER",
            recipient_id="TEST002_RECIPIENT",
            amount=1000.0,
            transaction_type=TransactionType.TRANSFER,
            timestamp=datetime(2026, 1, 16, 0, 0, 0, tzinfo=timezone.utc),
            account_age_days=100,
            account_balance_before=10000.0,
            is_new_recipient=False,
            sender_tx_count=5
        )
        
        result_23 = run_inference(tx_23)
        result_0 = run_inference(tx_0)
        
        # Fraud scores should be reasonably similar
        assert abs(result_23.combined_risk_score - result_0.combined_risk_score) < 0.2
    
    def test_new_recipient_increases_score(self):
        """Test that new recipient flag increases fraud risk score."""
        tx_known = IncomingTransaction(
            account_id="TEST001_SENDER",
            recipient_id="TEST002_RECIPIENT",
            amount=50000.0,
            transaction_type=TransactionType.TRANSFER,
            timestamp=datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            account_age_days=180,
            account_balance_before=100000.0,
            is_new_recipient=False,
            sender_tx_count=10
        )
        
        tx_new = IncomingTransaction(
            account_id="TEST001_SENDER",
            recipient_id="NEWRECIPIENT999",
            amount=50000.0,
            transaction_type=TransactionType.TRANSFER,
            timestamp=datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            account_age_days=180,
            account_balance_before=100000.0,
            is_new_recipient=True,
            sender_tx_count=10
        )
        
        result_known = run_inference(tx_known)
        result_new = run_inference(tx_new)
        
        # New recipient should score higher risk
        assert result_new.combined_risk_score > result_known.combined_risk_score
    
    def test_latency_under_budget(self, sample_transaction):
        """Test that inference latency remains within the SLA budget (<30ms)."""
        result = run_inference(sample_transaction)
        assert result.inference_latency_ms < 30.0
    
    def test_explanation_generated(self, suspicious_transaction):
        """Test that SHAP generates top features descriptions."""
        import numpy as np
        from app.inference import _run_shap, build_features
        feats = build_features(suspicious_transaction)
        feats_array = np.array(feats.to_numpy_array(), dtype=np.float32).reshape(1, -1)
        shap_features = _run_shap(feats_array)
        assert shap_features is not None
        assert len(shap_features) > 0
        assert "feature" in shap_features[0]
        assert "value" in shap_features[0]
        assert "impact" in shap_features[0]
    
    def test_large_amount_flag(self):
        """Test that large transaction amounts drive higher fraud risk scores."""
        tx_small = IncomingTransaction(
            account_id="TEST001_SENDER",
            recipient_id="TEST002_RECIPIENT",
            amount=1000.0,
            transaction_type=TransactionType.TRANSFER,
            timestamp=datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            account_age_days=180,
            account_balance_before=100000.0,
            is_new_recipient=False,
            sender_tx_count=10
        )
        
        tx_large = IncomingTransaction(
            account_id="TEST001_SENDER",
            recipient_id="TEST002_RECIPIENT",
            amount=100000.0,
            transaction_type=TransactionType.TRANSFER,
            timestamp=datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            account_age_days=180,
            account_balance_before=150000.0,
            is_new_recipient=False,
            sender_tx_count=10
        )
        
        result_small = run_inference(tx_small)
        result_large = run_inference(tx_large)
        
        # Large amount should have higher fraud score
        assert result_large.combined_risk_score > result_small.combined_risk_score



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
