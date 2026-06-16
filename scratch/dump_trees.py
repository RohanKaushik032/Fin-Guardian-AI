import sys
sys.path.insert(0, r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain")

from app.inference import registry
import xgboost as xgb

registry.load_all(artifacts_dir=r"c:\Users\rohan\OneDrive\Desktop\Fin_Gurdain\artifacts")
booster = registry.xgb_model.get_booster()

# Print the text dump of the first few trees
dump = booster.get_dump()
print(f"Total trees: {len(dump)}")
for idx, tree in enumerate(dump[:5]):
    print(f"\n--- Tree {idx} ---")
    print(tree)
