import sys
sys.path.insert(0, r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain")

from app.inference import registry, _run_xgboost, _run_autoencoder
from app.schemas.transaction import IncomingTransaction, TransactionType
from datetime import datetime, timezone
import numpy as np

registry.load_all(artifacts_dir=r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain\artifacts")

print("Sweeping amount with sender_zeroed = 1:")
for amt in [1.0, 5.0, 10.0, 50.0, 100.0, 500.0, 1000.0, 5000.0, 10000.0, 50000.0]:
    tx = IncomingTransaction(
        account_id="C_SENDER",
        recipient_id="C_RECIPIENT",
        amount=amt,
        transaction_type=TransactionType.TRANSFER,
        timestamp=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        device_id="dev_1",
        ip_address="127.0.0.1",
        latitude=12.97,
        longitude=77.59,
        account_age_days=180,
        account_balance_before=amt, # sender_zeroed = 1
        is_new_recipient=False,
        sender_tx_count=0
    )
    
    from app.utils.encoders import build_features
    feats = build_features(tx)
    feats_array = np.array(feats.to_numpy_array(), dtype=np.float32).reshape(1, -1)
    xgb_val = _run_xgboost(feats_array)
    ae_val = _run_autoencoder(feats_array)
    
    # Let's calculate using BOTH 0.05 and the correct 1.3025567531585693 thresholds
    ae_score_05 = min(ae_val / 0.05, 1.0)
    combined_05 = 0.70 * xgb_val + 0.30 * ae_score_05
    
    ae_score_ae = min(ae_val / 1.3025567531585693, 1.0)
    combined_ae = 0.70 * xgb_val + 0.30 * ae_score_ae
    
    print(f"amt={amt:7.1f} | xgb={xgb_val:.4f} | ae={ae_val:.4f} | combined(0.05)={combined_05:.4f} | combined(1.30)={combined_ae:.4f}")
