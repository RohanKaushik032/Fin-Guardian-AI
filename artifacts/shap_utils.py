import numpy as np
import pickle

def get_shap_explanation(model, explainer, feature_values, feature_names, top_n=3):
    shap_vals = explainer.shap_values(feature_values.reshape(1, -1))[0]
    ranked = sorted(zip(feature_names, feature_values.flatten(), shap_vals),
                    key=lambda x: abs(x[2]), reverse=True)
    return [{"feature": f, "value": round(float(v),4), "impact": round(float(i),4)}
            for f, v, i in ranked[:top_n]]
