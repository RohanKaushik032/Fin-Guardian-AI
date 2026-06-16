"""
app/schemas/transaction.py
──────────────────────────
Central data contract for Fin-Guardian AI.

Every field that enters or leaves the system is defined here.
Think of this like defining your DataFrame columns and dtypes —
except Pydantic validates the VALUES automatically at runtime.

If any field is wrong (negative amount, future timestamp, etc.)
Pydantic raises a clear error BEFORE any model ever sees bad data.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Enums (fixed categories — like pd.Categorical) ────────────────────────

class TransactionType(str, Enum):
    """
    Transaction types from PaySim dataset.
    In production, fraud ONLY occurs in TRANSFER and CASH_OUT.
    Any other type can be fast-approved without model inference.
    """
    CASH_IN   = "CASH_IN"
    CASH_OUT  = "CASH_OUT"
    DEBIT     = "DEBIT"
    PAYMENT   = "PAYMENT"
    TRANSFER  = "TRANSFER"


class RiskVerdict(str, Enum):
    """
    The three possible decisions from the hot path (Layer 1).

    APPROVE → transaction goes through immediately (~70% of cases)
    HOLD    → paused, async deep investigation triggered (Layers 2+3)
    DENY    → blocked immediately, customer notified with reason
    """
    APPROVE = "APPROVE"
    HOLD    = "HOLD"
    DENY    = "DENY"


class ChallengeType(str, Enum):
    """
    Layer 4: adaptive step-up challenge sent to the user.
    Escalates based on combined risk score.
    """
    NONE        = "NONE"          # score < HOLD threshold → no challenge
    TAP_CONFIRM = "TAP_CONFIRM"   # low suspicion → single tap confirmation
    BIOMETRIC   = "BIOMETRIC"     # medium suspicion → Face ID / fingerprint
    BEHAVIOURAL = "BEHAVIOURAL"   # high suspicion → swipe pattern check


# ── Incoming transaction (what the mobile app sends) ──────────────────────

class IncomingTransaction(BaseModel):
    """
    Raw transaction payload arriving at the FastAPI gateway.

    Every field has:
    - A Python type (str, float, bool, etc.)
    - Constraints (gt=0, min_length=5, etc.)
    - A description for auto-generated API docs

    Pydantic checks ALL of these automatically.
    You never write 'if amount < 0: raise ValueError' manually.
    """

    # ── Identity ────────────────────────────────────────────────────────
    transaction_id   : UUID     = Field(
        default_factory=uuid4,
        description="Unique transaction ID. Auto-generated if not provided."
    )
    account_id       : str      = Field(..., min_length=5, max_length=64,
                                        description="Sender account identifier.")
    recipient_id     : str      = Field(..., min_length=5, max_length=64,
                                        description="Recipient account identifier.")

    # ── Transaction details ─────────────────────────────────────────────
    amount           : float    = Field(..., gt=0, le=10_000_000,
                                        description="Amount in INR. Must be positive.")
    transaction_type : TransactionType
    timestamp        : datetime = Field(...,
                                        description="UTC timestamp of the transaction.")

    # ── Device & network context (optional — absence is itself a signal) ─
    device_id        : str | None   = Field(None, max_length=256)
    ip_address       : str | None   = Field(None)
    latitude         : float | None = Field(None, ge=-90,  le=90)
    longitude        : float | None = Field(None, ge=-180, le=180)

    # ── Account profile snapshot (sent by bank's core system) ───────────
    account_age_days        : int   = Field(..., ge=0,
                                            description="How old is this account in days.")
    account_balance_before  : float = Field(..., ge=0,
                                            description="Sender balance before this transaction.")
    is_new_recipient        : bool  = Field(...,
                                            description="True if sender has never paid this recipient before.")
    sender_tx_count         : int   = Field(default=0, ge=0,
                                            description="Number of previous transactions by this sender.")

    # ── Validators ──────────────────────────────────────────────────────

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_not_be_future(cls, v: datetime) -> datetime:
        """
        Temporal integrity — prevents data leakage from future events.

        In data science: if training data contains future information,
        your model gets unrealistically good. Same principle here —
        we reject timestamps that haven't happened yet.
        """
        # Make both timezone-aware for comparison
        now = datetime.now(timezone.utc)
        if v.tzinfo is None:
            # Assume UTC if no timezone provided
            from datetime import timezone as tz
            v = v.replace(tzinfo=tz.utc)
        if v > now:
            raise ValueError(
                f"Transaction timestamp {v} is in the future. "
                "Possible clock skew or replay attack."
            )
        return v

    @field_validator("amount")
    @classmethod
    def amount_must_be_finite(cls, v: float) -> float:
        """Reject NaN and infinity — they silently corrupt model inference."""
        if not math.isfinite(v):
            raise ValueError(
                "Transaction amount must be a finite number. "
                f"Got: {v}"
            )
        return round(v, 2)

    @model_validator(mode="after")
    def balance_must_cover_amount(self) -> "IncomingTransaction":
        """
        Basic sanity: you cannot send more than your balance.
        This is a model-level validator because it needs TWO fields.
        """
        if self.account_balance_before < self.amount:
            raise ValueError(
                f"Insufficient balance: ₹{self.account_balance_before:,.2f} "
                f"cannot cover ₹{self.amount:,.2f}"
            )
        return self


# ── Engineered features (what the ML models see) ──────────────────────────

class EngineeredFeatures(BaseModel):
    """
    The 19 features fed into XGBoost and the Autoencoder.

    These match EXACTLY the columns in train.csv from Notebook 03.
    """

    # Time — cyclical encoding (sin/cos so 11pm and midnight are neighbors)
    hour_sin                : float
    hour_cos                : float
    day_sin                 : float
    day_cos                 : float

    # Amount
    amount_log              : float   # log(1 + amount) — compresses skew
    amount_to_balance_ratio : float   # how much of balance is this? 0-1

    # Behavioral stats (replace PaySim leakage)
    tx_count_1h             : float
    tx_count_24h            : float
    avg_amount_7d           : float
    avg_amount_30d          : float
    recipient_seen_before   : float

    # Binary flags
    sender_zeroed           : int     # 1 if sender balance drained to 0
    dest_was_empty          : int     # 1 if dest account was at 0 before
    is_new_recipient        : int     # 1 if first-ever payment to this account

    # Missing data flags (absence of data IS a signal)
    has_location            : int     # 1 if GPS provided, 0 if missing
    has_device_id           : int     # 1 if device_id provided, 0 if missing

    # Account history
    sender_tx_count         : int     # how many txns has sender made before
    recipient_tx_count      : int     # how many times has recipient received

    # Transaction type
    type_encoded            : int     # TRANSFER=1, CASH_OUT=0

    def to_numpy_array(self) -> list[float]:
        """
        Returns features as an ordered list matching feature_list.json.
        Used by the inference engine to create the model input array.
        """
        return [
            self.hour_sin, self.hour_cos, self.day_sin, self.day_cos,
            self.amount_log, self.amount_to_balance_ratio,
            self.tx_count_1h, self.tx_count_24h,
            self.avg_amount_7d, self.avg_amount_30d,
            self.recipient_seen_before,
            self.sender_zeroed, self.dest_was_empty, self.is_new_recipient,
            self.has_location, self.has_device_id,
            self.sender_tx_count, self.recipient_tx_count,
            self.type_encoded,
        ]


# ── Inference result (what Layer 1 returns) ───────────────────────────────

class InferenceResult(BaseModel):
    """
    Output of the hot path: scores + SHAP explanation + verdict.

    This is returned to the mobile app AND sent to Kafka
    (if verdict is HOLD) for async deep investigation.
    """
    transaction_id           : UUID
    verdict                  : RiskVerdict
    challenge_type           : ChallengeType = ChallengeType.NONE

    # Model scores
    xgb_fraud_prob           : float = Field(..., ge=0, le=1,
                                             description="XGBoost fraud probability 0-1.")
    autoencoder_recon_error  : float = Field(..., ge=0,
                                             description="How far this tx deviates from normal baseline.")
    combined_risk_score      : float = Field(..., ge=0, le=1,
                                             description="Weighted combination of both model scores.")

    # SHAP explanation (regulatory requirement)
    shap_top_features        : list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Top 3 features driving this decision. "
            "Example: [{'feature': 'amount_to_balance_ratio', "
            "'value': 0.95, 'impact': 0.42}]"
        )
    )

    # Latency tracking
    inference_latency_ms     : float
    timestamp                : datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def get_human_readable_reason(self) -> str:
        """
        Produces a plain-English explanation for regulatory compliance.

        Example output:
        'Transaction flagged: amount_to_balance_ratio is unusually high
         (+0.42 impact), is_new_recipient contributed (+0.31 impact),
         sender_zeroed contributed (+0.19 impact).'
        """
        if not self.shap_top_features:
            return f"Transaction {self.verdict.value} by combined risk model."

        parts = []
        for feat in self.shap_top_features[:3]:
            direction = "toward fraud" if feat["impact"] > 0 else "toward legitimate"
            parts.append(
                f"{feat['feature']} (value={feat['value']:.3f}, "
                f"impact={feat['impact']:+.3f} {direction})"
            )
        return f"Decision: {self.verdict.value}. Key factors: {'; '.join(parts)}."


# ── Kafka event payload (sent on HOLD verdict) ────────────────────────────

class HoldEvent(BaseModel):
    """
    Message published to Kafka topic 'transactions.hold'
    when Layer 1 issues a HOLD verdict.

    Contains everything a Celery worker needs to investigate
    WITHOUT calling the gateway again.

    Think of Kafka like a persistent list:
    - Producer (gateway) writes events
    - Consumer (worker) reads and processes them
    - If worker crashes, event replays automatically
    """
    transaction      : IncomingTransaction
    features         : EngineeredFeatures
    inference_result : InferenceResult
    enqueued_at      : datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
