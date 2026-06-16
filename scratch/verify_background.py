import httpx
import time
import json

def test_flow():
    print("1. Triggering Midnight Ghost scenario...")
    res = httpx.get("http://127.0.0.1:8000/api/v1/transactions/test-midnight-ghost", timeout=15)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    
    data = res.json()
    txn_id = data["transaction_id"]
    print(f"   Inference complete. Verdict: {data['verdict']}. Txn ID: {txn_id}")
    
    print("2. Waiting 10 seconds for background tasks (LangGraph and explanation generation)...")
    time.sleep(10)
    
    print("3. Querying /api/v1/investigations/{transaction_id}...")
    res = httpx.get(f"http://127.0.0.1:8000/api/v1/investigations/{txn_id}", timeout=5)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    
    inv_data = res.json()
    print("   Investigation response loaded.")
    
    # Assertions
    assert inv_data["found"] is True, "Expected investigation results to be found in Redis"
    assert inv_data["explanation"] is not None, "AI Explanation is missing from Redis!"
    assert inv_data["forensic"] is not None, "Forensic report is missing from Redis!"
    
    explanation = inv_data["explanation"]
    forensic = inv_data["forensic"]
    
    print("\n--- AI EXPLANATION RESULTS ---")
    print(f"Analyst Summary: {explanation.get('analyst_summary')}")
    print(f"Reasons: {explanation.get('reasons')}")
    
    print("\n--- FORENSIC REPORT RESULTS ---")
    print(f"Confidence: {forensic.get('final_confidence')}")
    print(f"SHAP Features: {forensic.get('shap_features')}")
    print(f"Graph Risk: {forensic.get('graph_risk')}")
    print(f"Device Risk: {forensic.get('device_risk')}")
    print(f"VPN Detected: {forensic.get('ip_vpn')}")
    
    assert len(forensic.get("shap_features", [])) > 0, "SHAP features list is empty in the forensic report!"
    assert len(explanation.get("reasons", [])) > 0, "Reasons list is empty in the explanation!"
    
    print("\n✅ Verification Successful! All background tasks generated and cached correct data.")

if __name__ == "__main__":
    test_flow()
