import sys
sys.path.insert(0, r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain")

from app.inference import registry, _run_xgboost
from app.schemas.transaction import IncomingTransaction, TransactionType
from datetime import datetime, timezone
import numpy as np

registry.load_all(artifacts_dir=r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain\artifacts")

# Let's sweep amount_to_balance_ratio from 0.01 to 1.0 in steps of 0.01
# We will fix amount = 50000.0, transaction_type = TRANSFER, timestamp = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
# and try different values of account_balance_before to vary ratio.

amt = 50000.0
print("Sweeping ratio:")
for ratio in np.linspace(0.01, 1.0, 100):
    # ratio = amt / bal_before => bal_before = amt / ratio
    bal_before = amt / ratio
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
        account_balance_before=bal_before,
        is_new_recipient=False,
        sender_tx_count=0
    )
    
    from app.utils.encoders import build_features
    feats = build_features(tx)
    # We want to see how ratio changes the output
    feats_array = np.array(feats.to_numpy_array(), dtype=np.float32).reshape(1, -1)
    xgb_val = _run_xgboost(feats_array)
    # Let's print unique predictions
    print(f"ratio={ratio:.4f} | bal_before={bal_before:.1f} | sender_zeroed={feats.sender_zeroed} | xgb={xgb_val:.4f}")
