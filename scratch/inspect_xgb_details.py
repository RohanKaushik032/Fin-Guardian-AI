import sys
sys.path.insert(0, r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain")

from app.inference import registry
import xgboost as xgb
import numpy as np

registry.load_all(artifacts_dir=r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain\artifacts")
booster = registry.xgb_model.get_booster()

print("Number of trees:", len(booster.get_dump()))
print("Feature names:", booster.feature_names)

# Let's generate a grid of test feature arrays and see all unique predictions
# 16 features:
# hour_sin, hour_cos, day_sin, day_cos, amount_log, amount_to_balance_ratio,
# balance_error_orig_log, balance_error_dest_log, sender_zeroed, dest_was_empty,
# is_new_recipient, has_location, has_device_id, sender_tx_count, recipient_tx_count, type_encoded

# We can try random uniform features or specific features
np.random.seed(42)
test_arrays = np.random.uniform(-1, 1, size=(500, 16))
# For boolean fields, let's make them 0 or 1
for i in [8, 9, 10, 11, 12, 15]:
    test_arrays[:, i] = np.random.choice([0.0, 1.0], size=500)

dmat = xgb.DMatrix(test_arrays.astype(np.float32), feature_names=booster.feature_names)
preds = booster.predict(dmat)
unique_preds = np.unique(preds)
print("Unique predictions on random grid:", unique_preds)
print("Min prediction:", np.min(preds))
print("Max prediction:", np.max(preds))
