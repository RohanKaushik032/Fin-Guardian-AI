import sys
sys.path.insert(0, r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain")

from app.inference import registry, _run_autoencoder, _run_xgboost
from app.schemas.transaction import IncomingTransaction, TransactionType
from datetime import datetime, timezone
import numpy as np

registry.load_all(artifacts_dir=r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain\artifacts")

# Let's search for combination of features that gives the minimum reconstruction error
best_error = 99999.0
best_tx = None

# We can scan amount, hour, day, is_new_recipient, has_device_id, has_location, recipient_tx_count
for amount in [100, 1000, 5000, 20000, 50000, 100000, 150000, 250000]:
    for hour in [0, 6, 12, 18, 23]:
        for day in [0, 3, 6]:
            for is_new in [True, False]:
                for device in [True, False]:
                    for loc in [True, False]:
                        for rec_count in [0, 1, 5, 10, 20]:
                            # Construct IncomingTransaction
                            tx = IncomingTransaction(
                                account_id="C_SENDER",
                                recipient_id="C_RECIPIENT",
                                amount=float(amount),
                                transaction_type=TransactionType.TRANSFER,
                                timestamp=datetime(2026, 6, day + 1, hour, 0, 0, tzinfo=timezone.utc),
                                device_id="dev_1" if device else None,
                                ip_address="127.0.0.1",
                                latitude=12.97 if loc else None,
                                longitude=77.59 if loc else None,
                                account_age_days=180,
                                account_balance_before=float(amount * 1.5),
                                is_new_recipient=is_new,
                                sender_tx_count=0
                            )
                            # Run autoencoder. Note: run_inference does enrichment, but we can call our local functions
                            from app.utils.encoders import build_features
                            feats = build_features(tx)
                            # Override recipient_tx_count and dest_was_empty like in run_inference
                            feats.recipient_tx_count = rec_count
                            feats.dest_was_empty = 1 if rec_count == 0 else 0
                            
                            feats_array = np.array(feats.to_numpy_array(), dtype=np.float32).reshape(1, -1)
                            err = _run_autoencoder(feats_array)
                            xgb = _run_xgboost(feats_array)
                            
                            # calculate combined score
                            ae_score = min(err / 0.05, 1.0)
                            combined = 0.70 * xgb + 0.30 * ae_score
                            
                            if err < best_error:
                                best_error = err
                                best_tx = (amount, hour, day, is_new, device, loc, rec_count, err, xgb, combined)

print("Best error result:")
print(f"  amount: {best_tx[0]}")
print(f"  hour: {best_tx[1]}")
print(f"  day: {best_tx[2]}")
print(f"  is_new: {best_tx[3]}")
print(f"  device: {best_tx[4]}")
print(f"  loc: {best_tx[5]}")
print(f"  rec_count: {best_tx[6]}")
print(f"  recon_error: {best_tx[7]:.6f}")
print(f"  xgb_prob: {best_tx[8]:.4f}")
print(f"  combined_score: {best_tx[9]:.4f}")
