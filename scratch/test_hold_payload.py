import sys
sys.path.insert(0, r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain")

from app.inference import registry, run_inference
from app.schemas.transaction import IncomingTransaction, TransactionType
from datetime import datetime, timezone

registry.load_all(artifacts_dir=r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain\artifacts")

tx = IncomingTransaction(
    account_id="C_SENDER_TEST_HOLD",
    recipient_id="C_RECIPIENT_TEST_HOLD",
    amount=2000000.0,
    transaction_type=TransactionType.TRANSFER,
    timestamp=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    device_id="dev_test_device",
    ip_address="127.0.0.1",
    latitude=12.9716,
    longitude=77.5946,
    account_age_days=180,
    account_balance_before=2100000.0,
    is_new_recipient=False,
    sender_tx_count=0
)

res = run_inference(tx)
print("Verification result:")
print(f"  verdict: {res.verdict.value}")
print(f"  challenge_type: {res.challenge_type.value}")
print(f"  xgb_fraud_prob: {res.xgb_fraud_prob:.4f}")
print(f"  autoencoder_recon_error: {res.autoencoder_recon_error:.6f}")
print(f"  combined_risk_score: {res.combined_risk_score:.4f}")
