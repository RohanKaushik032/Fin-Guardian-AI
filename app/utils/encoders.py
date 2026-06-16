"""
app/utils/encoders.py
─────────────────────
Cyclical Time Transformation Engine + Live Feature Builder

This file bridges the gap between:
  - What the mobile app sends  (IncomingTransaction — raw data)
  - What the ML models expect  (EngineeredFeatures — 16 numbers)

In Notebook 03 we built features from a CSV using pandas.
In production we must build the EXACT same features from a single
live transaction object, in under 2ms, with no pandas overhead.

CRITICAL RULE: Every feature here must match Notebook 03 exactly.
If Notebook 03 used log1p(amount), this must use log1p(amount).
Any mismatch causes silent prediction errors — the model receives
different numbers than it was trained on.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from app.schemas.transaction import EngineeredFeatures, IncomingTransaction
from app.features.feature_store import feature_store


# ── Cyclical encoding functions ───────────────────────────────────────────

def encode_cyclic(value: float, period: float) -> tuple[float, float]:
    """
    Encode a periodic value as (sin, cos) pair.

    WHY: Raw hour numbers break ML models.
    Hour=23 and Hour=0 are 1 hour apart but numerically look 23 apart.
    sin/cos maps them onto a circle where they are neighbors.

    Formula:
        sin(2π × value / period)
        cos(2π × value / period)

    Examples:
        encode_cyclic(23, 24) → (-0.259, 0.966)
        encode_cyclic(0,  24) → (0.0,   1.0)
        These are now CLOSE — correctly showing 11pm ≈ midnight

    Args:
        value  : the raw value (e.g. hour=23, day=6)
        period : the full cycle length (24 for hours, 7 for weekday)

    Returns:
        (sin_value, cos_value) — two features replacing the original one
    """
    angle = 2.0 * math.pi * value / period
    return math.sin(angle), math.cos(angle)


# ── PaySim step → real time conversion ───────────────────────────────────

def timestamp_to_paysim_step_features(ts: datetime) -> dict[str, float]:
    """
    Convert a real datetime to PaySim-compatible cyclical features.

    PaySim used 'step' (hours since simulation start).
    In production we have real timestamps.
    We extract hour-of-day and day-of-week, then apply cyclical encoding.

    Args:
        ts: transaction datetime (UTC)

    Returns:
        dict with hour_sin, hour_cos, day_sin, day_cos
    """
    # Ensure timezone-aware
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    hour        = ts.hour                    # 0-23
    day_of_week = ts.weekday()               # 0=Monday, 6=Sunday

    hour_sin, hour_cos = encode_cyclic(hour,        24)
    day_sin,  day_cos  = encode_cyclic(day_of_week,  7)

    return {
        "hour_sin": hour_sin,
        "hour_cos": hour_cos,
        "day_sin" : day_sin,
        "day_cos" : day_cos,
    }


# ── Main feature builder ──────────────────────────────────────────────────

def build_features(tx: IncomingTransaction) -> EngineeredFeatures:
    """
    Build all 19 engineered features from a live IncomingTransaction.

    This is called on EVERY transaction on the hot path.
    It must complete in under 2ms — no database calls, no I/O.
    Everything is computed purely from the transaction payload and Redis feature store.
    """

    # ── Time features ────────────────────────────────────────────
    time_feats = timestamp_to_paysim_step_features(tx.timestamp)

    # ── Amount (log-transformed) ───────────────────────────────────
    amount_log = math.log1p(tx.amount)

    # ── Amount to balance ratio ────────────────────────────────────
    if tx.account_balance_before > 0:
        ratio = tx.amount / tx.account_balance_before
    else:
        ratio = 1.0   # zero balance sending anything = 100% of balance
    amount_to_balance_ratio = min(ratio, 1.0)

    # ── Retrieve and Record Rolling Features from Feature Store ───
    rolling_feats = feature_store.get_rolling_features(tx.account_id, tx.recipient_id, tx.timestamp)
    feature_store.record_transaction(tx.account_id, tx.recipient_id, tx.amount, tx.timestamp)

    # ── Sender zeroed ──────────────────────────────────────────────
    # Will balance reach exactly 0 after this transaction?
    expected_new_balance = tx.account_balance_before - tx.amount
    sender_zeroed = 1 if abs(expected_new_balance) < 0.01 else 0

    # ── Dest was empty ────────────────────────────────────────────
    # Will be enriched by feature store or defaults to 0
    dest_was_empty = 0

    # ── Is new recipient ──────────────────────────────────────────
    is_new_recipient = 1 if tx.is_new_recipient else 0

    # ── Missing data flags ─────────────────────────────────────
    has_location  = 1 if (tx.latitude is not None and tx.longitude is not None) else 0
    has_device_id = 1 if tx.device_id is not None else 0

    # ── Sender transaction count ──────────────────────────────────
    sender_tx_count = tx.sender_tx_count

    # ── Recipient transaction count ──────────────────────────────
    # Set to 0 default — enriched by feature store in Phase 4
    recipient_tx_count = 0

    # ── Transaction type encoding ─────────────────────────────────
    type_encoded = 1 if tx.transaction_type.value == "TRANSFER" else 0

    return EngineeredFeatures(
        hour_sin                = time_feats["hour_sin"],
        hour_cos                = time_feats["hour_cos"],
        day_sin                 = time_feats["day_sin"],
        day_cos                 = time_feats["day_cos"],
        amount_log              = amount_log,
        amount_to_balance_ratio = amount_to_balance_ratio,
        tx_count_1h             = rolling_feats["tx_count_1h"],
        tx_count_24h            = rolling_feats["tx_count_24h"],
        avg_amount_7d           = rolling_feats["avg_amount_7d"],
        avg_amount_30d          = rolling_feats["avg_amount_30d"],
        recipient_seen_before   = rolling_feats["recipient_seen_before"],
        sender_zeroed           = sender_zeroed,
        dest_was_empty          = dest_was_empty,
        is_new_recipient        = is_new_recipient,
        has_location            = has_location,
        has_device_id           = has_device_id,
        sender_tx_count         = sender_tx_count,
        recipient_tx_count      = recipient_tx_count,
        type_encoded            = type_encoded,
    )
