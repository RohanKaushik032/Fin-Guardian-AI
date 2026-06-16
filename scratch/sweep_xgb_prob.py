import sys
sys.path.insert(0, r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain")

from app.inference import registry, _run_xgboost, _run_autoencoder
from app.schemas.transaction import IncomingTransaction, TransactionType
from datetime import datetime, timezone
import numpy as np

registry.load_all(artifacts_dir=r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain\artifacts")

# Features to sweep:
# - transaction_type: TRANSFER, CASH_OUT
# - amount: [1000, 5000, 10000, 20000, 50000, 100000, 250000]
# - hour: [0, 4, 8, 12, 16, 20]
# - day: [0, 2, 4, 6] (to vary day_sin/day_cos)
# - is_new_recipient: [True, False]
# - device_id: ["dev", None]
# - location: [True, False]
# - account_balance_before: [0.0, 1000.0, 10000.0, 100000.0] (varying ratio and sender_zeroed)
# - sender_tx_count: [0, 1, 5, 10]
# - recipient_tx_count: [0, 1, 5, 10]

# Let's run a sweep
found_count = 0
for tx_type in [TransactionType.TRANSFER, TransactionType.CASH_OUT]:
    for amt in [1000.0, 5000.0, 15000.0, 50000.0, 120000.0]:
        for hour in [2, 9, 14, 21]:
            for is_new in [True, False]:
                for has_device in [True, False]:
                    for bal in [amt, amt + 1000.0, amt + 50000.0]:
                        for snd_count in [0, 2]:
                            for rec_count in [0, 2]:
                                tx = IncomingTransaction(
                                    account_id="C_SENDER",
                                    recipient_id="C_RECIPIENT",
                                    amount=amt,
                                    transaction_type=tx_type,
                                    timestamp=datetime(2026, 1, 15, hour, 0, 0, tzinfo=timezone.utc),
                                    device_id="dev_1" if has_device else None,
                                    ip_address="127.0.0.1",
                                    latitude=12.97 if has_device else None,
                                    longitude=77.59 if has_device else None,
                                    account_age_days=180,
                                    account_balance_before=bal,
                                    is_new_recipient=is_new,
                                    sender_tx_count=snd_count
                                )
                                from app.utils.encoders import build_features
                                feats = build_features(tx)
                                feats.recipient_tx_count = rec_count
                                feats.dest_was_empty = 1 if rec_count == 0 else 0
                                
                                feats_array = np.array(feats.to_numpy_array(), dtype=np.float32).reshape(1, -1)
                                xgb_val = _run_xgboost(feats_array)
                                ae_val = _run_autoencoder(feats_array)
                                
                                ae_score = min(ae_val / 0.05, 1.0)
                                combined = 0.70 * xgb_val + 0.30 * ae_score
                                
                                # We want a HOLD verdict: combined in [0.4462, 0.6300)
                                if 0.4462 <= combined < 0.6300:
                                    print(f"HOLD MATCH: type={tx_type.value}, amt={amt}, hour={hour}, is_new={is_new}, device={has_device}, bal={bal}, snd_cnt={snd_count}, rec_cnt={rec_count} -> xgb={xgb_val:.4f}, ae_err={ae_val:.4f}, combined={combined:.4f}")
                                    found_count += 1
                                    if found_count >= 20:
                                        print("Found 20 combinations. Stopping sweep.")
                                        sys.exit(0)

if found_count == 0:
    print("No matching combination found in this grid.")
