#!/usr/bin/env python
"""Quick test script for the Fin-Guardian API"""

import httpx
import time
import json

# Give server a moment to be ready
time.sleep(2)

print("\n" + "="*60)
print("FIN-GUARDIAN API TEST")
print("="*60 + "\n")

try:
    print("1️⃣  Testing /health endpoint...")
    response = httpx.get('http://127.0.0.1:8000/health', timeout=5)
    if response.status_code == 200:
        print("   ✅ Health check: PASSED")
        data = response.json()
        print(f"   Status: {data.get('status')}")
        print(f"   Models loaded: {data.get('models_loaded')}")
        print(f"   Service: {data.get('service')}")
        print(f"   Version: {data.get('version')}")
    else:
        print(f"   ❌ Unexpected status code: {response.status_code}")
        
except Exception as e:
    print(f"   ❌ Error: {e}")

try:
    print("\n2️⃣  Testing /api/v1/transactions/test-midnight-ghost...")
    response = httpx.get('http://127.0.0.1:8000/api/v1/transactions/test-midnight-ghost', timeout=10)
    if response.status_code == 200:
        print("   ✅ Midnight Ghost test: PASSED")
        data = response.json()
        print(f"   Verdict: {data.get('verdict')}")
        print(f"   Combined Risk Score: {data.get('combined_risk_score'):.4f}")
        print(f"   XGBoost Fraud Prob: {data.get('xgb_fraud_prob'):.4f}")
        print(f"   Inference Latency: {data.get('inference_latency_ms'):.2f}ms")
        if data.get('shap_top_features'):
            print("   Top Features:")
            for feat in data.get('shap_top_features', [])[:3]:
                print(f"      - {feat['feature']}: value={feat['value']:.4f}, impact={feat['impact']:+.4f}")
    else:
        print(f"   ❌ Unexpected status code: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "="*60)
print("✅ ALL TESTS COMPLETED")
print("="*60 + "\n")
