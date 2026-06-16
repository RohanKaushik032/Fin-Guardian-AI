import pytest
from unittest.mock import patch
import numpy as np
from app.inference import registry

def mock_run_xgboost(features_array: np.ndarray) -> float:
    # Indices based on 19-feature list:
    # 4: amount_log, 13: is_new_recipient
    amount_log = features_array[0][4]
    is_new_recipient = features_array[0][13]
    
    prob = 0.05
    if amount_log > 10.0:
        prob += 0.4
    if is_new_recipient == 1:
        prob += 0.35
    # pyrefly: ignore [unnecessary-type-conversion]
    return float(prob)

def mock_run_autoencoder(features_array: np.ndarray) -> float:
    # Indices based on 19-feature list:
    # 4: amount_log, 16: sender_tx_count
    amount_log = features_array[0][4]
    sender_tx_count = features_array[0][16]
    
    error = 0.02
    if sender_tx_count > 5:
        error += 0.1
    if amount_log > 11.0:
        error += 0.2
    # pyrefly: ignore [unnecessary-type-conversion]
    return float(error)

def mock_run_shap(features_array: np.ndarray, top_n: int = 3) -> list[dict]:
    return [
        {"feature": "amount_log", "value": 11.43, "impact": 0.4},
        {"feature": "is_new_recipient", "value": 1.0, "impact": 0.35},
        {"feature": "dest_was_empty", "value": 1.0, "impact": 0.05}
    ]

@pytest.fixture(scope="session", autouse=True)
def mock_services():
    """Mock ML model inferences and graph database enrichment globally for all tests."""
    # Ensure registry states are mocked as loaded
    registry._loaded = True
    registry.metadata = {
        "hold_threshold": 0.4462,
        "deny_threshold": 0.6300
    }
    registry.feature_names = [
        "hour_sin", "hour_cos", "day_sin", "day_cos",
        "amount_log", "amount_to_balance_ratio",
        "tx_count_1h", "tx_count_24h",
        "avg_amount_7d", "avg_amount_30d",
        "recipient_seen_before",
        "sender_zeroed", "dest_was_empty", "is_new_recipient",
        "has_location", "has_device_id",
        "sender_tx_count", "recipient_tx_count",
        "type_encoded"
    ]
    
    with patch("app.inference._run_xgboost", side_effect=mock_run_xgboost), \
         patch("app.inference._run_autoencoder", side_effect=mock_run_autoencoder), \
         patch("app.inference._run_shap", side_effect=mock_run_shap), \
         patch("app.inference.enricher.get_recipient_tx_count", return_value=0):
        yield

