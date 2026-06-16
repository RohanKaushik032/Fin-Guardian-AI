import sys
sys.path.insert(0, r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain")

import pickle
from pathlib import Path

base = Path(r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain\artifacts")
with open(base / "shap_explainer.pkl", "rb") as f:
    explainer = pickle.load(f)

print("Explainer type:", type(explainer))
if hasattr(explainer, "expected_value"):
    print("Expected value:", explainer.expected_value)
if hasattr(explainer, "model"):
    print("Model type:", type(explainer.model))
    if hasattr(explainer.model, "num_features"):
        print("Num features:", explainer.model.num_features)
    elif hasattr(explainer.model, "original_model"):
        orig = explainer.model.original_model
        print("Original model type:", type(orig))
        if hasattr(orig, "n_features_in_"):
            print("n_features_in_:", orig.n_features_in_)
        elif hasattr(orig, "num_features"):
            print("num_features:", orig.num_features)
