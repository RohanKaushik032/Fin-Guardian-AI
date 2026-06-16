import sys
sys.path.insert(0, r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain")

from app.inference import registry, _run_xgboost, _run_autoencoder
from app.schemas.transaction import IncomingTransaction, TransactionType
from datetime import datetime, timezone
import numpy as np

registry.load_all(artifacts_dir=r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain\artifacts")

# Let's test a transaction with amount = 2,000,000 (which is > 1.77 million)
# and balance_before = 3,000,000 (so sender_zeroed = 0)
# and try varying type (TRANSFER vs CASH_OUT) and other features.

for tx_type in [TransactionType.TRANSFER, TransactionType.CASH_OUT]:
    for amt in [100000.0, 500000.0, 1000000.0, 2000000.0, 5000000.0]:
        tx = IncomingTransaction(
            account_id="C_SENDER",
            recipient_id="C_RECIPIENT",
            amount=amt,
            transaction_type=tx_type,
            timestamp=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            device_id="dev_1",
            ip_address="127.0.0.1",
            latitude=12.97,
            longitude=77.59,
            account_age_days=180,
            account_balance_before=amt + 100000.0, # sender_zeroed = 0
            is_new_recipient=False,
            sender_tx_count=0
        )
        from app.utils.encoders import build_features
        feats = build_features(tx)
        feats_array = np.array(feats.to_numpy_array(), dtype=np.float32).reshape(1, -1)
        xgb_val = _run_xgboost(feats_array)
        ae_val = _run_autoencoder(feats_array)
        
        ae_score = min(ae_val / 1.3025567531585693, 1.0)
        combined = 0.70 * xgb_val + 0.30 * ae_score
        
        print(f"type={tx_type.value} | amt={amt:10.1f} | xgb={xgb_val:.4f} | ae={ae_val:.4f} | combined={combined:.4f}")
