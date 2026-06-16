import asyncio
from datetime import datetime, timezone
from app.schemas.transaction import IncomingTransaction, InferenceResult, RiskVerdict
from app.main import _run_detective_and_push

async def main():
    tx = IncomingTransaction(
        account_id             = "C_PRIYA_STUDENT_001",
        recipient_id           = "C_UNKNOWN_RECIPIENT_999",
        amount                 = 83148.0,
        transaction_type       = "TRANSFER",
        timestamp              = datetime(2026, 1, 15, 23, 45, 0, tzinfo=timezone.utc),
        device_id              = None,
        ip_address             = None,
        latitude               = None,
        longitude              = None,
        account_age_days       = 180,
        account_balance_before = 83148.0,
        is_new_recipient       = True,
        sender_tx_count        = 1,
    )
    result = InferenceResult(
        transaction_id          = tx.transaction_id,
        verdict                 = RiskVerdict.DENY,
        xgb_fraud_prob          = 0.8,
        autoencoder_recon_error = 0.08,
        combined_risk_score     = 0.85,
        shap_top_features       = [],
        inference_latency_ms    = 3.5,
    )
    
    print("Running _run_detective_and_push...")
    try:
        await _run_detective_and_push(tx, result)
        print("Done!")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
