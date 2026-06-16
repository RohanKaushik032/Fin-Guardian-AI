"""
app/agents/tools/risk_matrix.py
────────────────────────────────
Rule-based risk matrix fallback for the Fraud Detective agent.
Used when external tools (IP lookup, Neo4j) fail or time out.
Ensures the agent never hangs — it always returns a verdict.
"""

from __future__ import annotations


def evaluate_risk_matrix(
    amount: float,
    account_age_days: int,
    is_new_recipient: bool,
    sender_tx_count: int,
    hour_of_day: int,
    has_device: bool,
    has_gps: bool,
) -> dict:
    """
    Rule-based fallback risk assessment.
    Returns a verdict and structured risk factors without requiring any external services.

    Used as:
    1. Fallback when external tools fail
    2. Cross-validation for agent findings
    """
    risk_score = 0.0
    risk_factors: list[str] = []

    # Amount heuristics
    if amount > 50000:
        risk_score += 0.25
        risk_factors.append(f"High transaction amount: ₹{amount:,.0f}")
    if amount > 100000:
        risk_score += 0.15
        risk_factors.append("Very high amount (>₹1 lakh)")

    # Account age
    if account_age_days < 90:
        risk_score += 0.20
        risk_factors.append(f"Young account: {account_age_days} days old")
    elif account_age_days < 180:
        risk_score += 0.10
        risk_factors.append(f"Relatively new account: {account_age_days} days")

    # Recipient
    if is_new_recipient:
        risk_score += 0.20
        risk_factors.append("First-time recipient — no transaction history")

    # Transaction velocity
    if sender_tx_count < 5:
        risk_score += 0.15
        risk_factors.append(f"Low activity account: only {sender_tx_count} prior transactions")

    # Time of day (nighttime transactions are higher risk)
    if 0 <= hour_of_day <= 5 or 22 <= hour_of_day <= 23:
        risk_score += 0.10
        risk_factors.append(f"Unusual hour: {hour_of_day:02d}:00 (nighttime window)")

    # Missing device / GPS (Midnight Ghost signals)
    if not has_device:
        risk_score += 0.20
        risk_factors.append("No device ID — transaction may originate from software")
    if not has_gps:
        risk_score += 0.10
        risk_factors.append("No GPS data — user location unverifiable")

    # Clamp to [0, 1]
    risk_score = min(1.0, risk_score)

    # Classify
    if risk_score >= 0.7:
        verdict = "DENY"
        confidence = "HIGH"
    elif risk_score >= 0.45:
        verdict = "HOLD"
        confidence = "MEDIUM"
    else:
        verdict = "APPROVE"
        confidence = "HIGH"

    return {
        "risk_score": round(risk_score, 3),
        "verdict": verdict,
        "confidence": confidence,
        "risk_factors": risk_factors,
        "factor_count": len(risk_factors),
        "summary": (
            f"Rule-based assessment: {verdict} (score={risk_score:.2f}, confidence={confidence}). "
            f"Key factors: {'; '.join(risk_factors[:3]) if risk_factors else 'None identified'}."
        ),
    }
