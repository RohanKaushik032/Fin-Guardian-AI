"""
app/inference.py
────────────────
The Hot Path Inference Engine — Layer 1 of Fin-Guardian AI

Uses XGBoost native .json model (NOT ONNX Runtime).
XGBoost 3.x saves .onnx in its own format which is incompatible
with ONNX Runtime. The .json model works perfectly at ~3ms per call.
"""

from __future__ import annotations

from pyexpat import features
import time
import pickle
import json
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import xgboost as xgb
import shap

from loguru import logger

from app.schemas.transaction import (
    ChallengeType,
    EngineeredFeatures,
    IncomingTransaction,
    InferenceResult,
    RiskVerdict,
    TransactionType,
)
from app.utils.encoders import build_features
from app.services.feature_enrichment import enricher

# ── Autoencoder architecture (must match Notebook 05 exactly) ─────────────

class FraudAutoencoder(nn.Module):
    """
    Same architecture as Notebook 05.
    Architecture: 16 → 12 → 8 → 4 → 8 → 12 → 16

    IMPORTANT: This must match Notebook 05 EXACTLY.
    Any difference in layers means the saved weights won't load.
    """

    def __init__(self, n_features: int):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(n_features, 12), nn.BatchNorm1d(12), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(12, 8),          nn.BatchNorm1d(8),  nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(8, 4),           nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(4, 8),   nn.BatchNorm1d(8),  nn.ReLU(),
            nn.Linear(8, 12),  nn.BatchNorm1d(12), nn.ReLU(),
            nn.Linear(12, n_features), nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(x))


# ── Model registry ─────────────────────────────────────────────────────────

class ModelRegistry:
    """
    Holds all loaded model artifacts in memory.

    Loaded ONCE at startup via load_all().
    Every request reuses the same loaded models — never loads from disk again.
    This is what keeps inference fast.
    """

    def __init__(self):
        # XGBoost native model (replaces onnx_session)
        self.xgb_model      : Optional[xgb.XGBClassifier]  = None
        self.autoencoder    : Optional[FraudAutoencoder]    = None
        self.scaler         : Optional[object]              = None
        self.shap_explainer : Optional[shap.TreeExplainer]  = None
        self.feature_names  : Optional[list[str]]           = None
        self.metadata       : Optional[dict]                = None
        self.device         : torch.device                  = torch.device("cpu")
        self._loaded        : bool                          = False

    def load_all(self, artifacts_dir: str = "artifacts") -> None:
        """
        Load all artifacts from disk into memory.
        Called ONCE when FastAPI starts (lifespan event).
        """
        base = Path(artifacts_dir)
        if not base.exists():
            fallback = Path(__file__).resolve().parent.parent / "artifacts"
            if fallback.exists():
                base = fallback
        t0   = time.perf_counter()

        logger.info("Loading model artifacts from: {}", base.resolve())

        # ── 1. Feature list ───────────────────────────────────────────
        with open(base / "feature_list.json") as f:
            feat_meta = json.load(f)
        self.feature_names = feat_meta["features"]
        logger.info("Feature list loaded: {} features", len(self.feature_names))

        # ── 2. Model metadata (thresholds) ────────────────────────────
        with open(base / "model_metadata.json") as f:
            self.metadata = json.load(f)
        logger.info(
            "Thresholds loaded: HOLD={} DENY={}",
            self.metadata["hold_threshold"],
            self.metadata["deny_threshold"],
        )

        # ── 3. XGBoost native model (.json) ───────────────────────────
        # We use .json NOT .onnx because XGBoost 3.x saves .onnx in its
        # own proprietary format that ONNX Runtime cannot read.
        json_path = base / "xgboost_fraud.json"
        self.xgb_model = xgb.XGBClassifier()
        self.xgb_model.load_model(str(json_path))
        logger.info("XGBoost loaded from: {}", json_path.name)

        # ── 4. Autoencoder ────────────────────────────────────────────
        ae_path    = base / "autoencoder_best.pt"
        n_features = len(self.feature_names)
        self.autoencoder = FraudAutoencoder(n_features)
        state = torch.load(str(ae_path), map_location=self.device)
        self.autoencoder.load_state_dict(state)
        self.autoencoder.eval()   # disable Dropout for inference
        logger.info("Autoencoder loaded: {} features", n_features)

        # ── 5. Feature scaler (for autoencoder input) ─────────────────
        with open(base / "feature_scaler.pkl", "rb") as f:
            self.scaler = pickle.load(f)
        logger.info("Feature scaler loaded")

        # ── 6. SHAP explainer ─────────────────────────────────────────
        with open(base / "shap_explainer.pkl", "rb") as f:
            self.shap_explainer = pickle.load(f)
        logger.info("SHAP explainer loaded")

        elapsed = (time.perf_counter() - t0) * 1000
        self._loaded = True
        logger.info("All artifacts loaded in {:.1f}ms — ready for inference", elapsed)

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def hold_threshold(self) -> float:
        # pyrefly: ignore [unsupported-operation]
        return float(self.metadata["hold_threshold"])

    @property
    def deny_threshold(self) -> float:
        # pyrefly: ignore [unsupported-operation]
        return float(self.metadata["deny_threshold"])

    @property
    def recon_error_threshold(self) -> float:
        return 0.05


# Global singleton — imported by main.py
registry = ModelRegistry()


# ── Inference functions ────────────────────────────────────────────────────

def _map_19_to_16(features_array: np.ndarray) -> np.ndarray:
    """
    Maps 19-feature EngineeredFeatures array to the 16-feature array expected by the models.
    Removes PaySim leakage by setting balance_error_orig_log and balance_error_dest_log to 0.0.
    """
    if features_array.shape[1] == 16:
        return features_array

    row = features_array[0]
    mapped = np.array([
        row[0],   # hour_sin
        row[1],   # hour_cos
        row[2],   # day_sin
        row[3],   # day_cos
        row[4],   # amount_log
        row[5],   # amount_to_balance_ratio
        0.0,      # balance_error_orig_log (leakage neutralized)
        0.0,      # balance_error_dest_log (neutralized leakage)
        row[11],  # sender_zeroed
        row[12],  # dest_was_empty
        row[13],  # is_new_recipient
        row[14],  # has_location
        row[15],  # has_device_id
        row[16],  # sender_tx_count
        row[17],  # recipient_tx_count
        row[18],  # type_encoded
    ], dtype=np.float32).reshape(1, -1)
    return mapped


def _run_xgboost(features_array: np.ndarray) -> float:
    """
    Run XGBoost inference using native .json model.
    ~3ms per prediction — within the 30ms SLA budget.

    Args:
        features_array: shape (1, 19) float32 numpy array

    Returns:
        fraud probability 0.0 - 1.0
    """
    if not registry.is_loaded or registry.xgb_model is None:
        registry.load_all()
    mapped_array = _map_19_to_16(features_array)
    booster = registry.xgb_model.get_booster()
    dmat = xgb.DMatrix(mapped_array.astype(np.float32), feature_names=booster.feature_names)
    prob_val = float(booster.predict(dmat)[0])
    return max(0.0, min(1.0, prob_val))


def _run_autoencoder(features_array: np.ndarray) -> float:
    """
    Run Autoencoder and return reconstruction error.

    High reconstruction error = transaction does not look normal
    = possible novel fraud that XGBoost has never seen before.

    Args:
        features_array: shape (1, 19) float32 numpy array (raw, not scaled)

    Returns:
        reconstruction error (mean squared error, higher = more anomalous)
    """
    if not registry.is_loaded or registry.autoencoder is None or registry.scaler is None:
        registry.load_all()
    mapped_array = _map_19_to_16(features_array)
    # pyrefly: ignore [missing-attribute]
    scaled = registry.scaler.transform(mapped_array).astype(np.float32)
    tensor = torch.FloatTensor(scaled).to(registry.device)

    with torch.no_grad():
        # pyrefly: ignore [not-callable]
        reconstructed = registry.autoencoder(tensor)
        error = torch.mean((tensor - reconstructed) ** 2).item()

    return float(error)


def _run_shap(features_array: np.ndarray, top_n: int = 3) -> list[dict]:
    """
    Generate SHAP explanation for the transaction.

    Returns top_n features driving this prediction.
    This is the human-readable reason required by financial regulators.
    Never crashes the hot path — returns empty list on any failure.

    Args:
        features_array: shape (1, 19) float32 numpy array
        top_n: number of top features to return

    Returns:
        [{'feature': str, 'value': float, 'impact': float}, ...]
    """
    try:
        if not registry.is_loaded or registry.shap_explainer is None:
            registry.load_all()
        mapped_array = _map_19_to_16(features_array)
        # pyrefly: ignore [missing-attribute]
        shap_vals = registry.shap_explainer.shap_values(mapped_array)[0]
        feat_vals = mapped_array.flatten()

        ranked = sorted(
            # pyrefly: ignore [bad-argument-type]
            zip(registry.feature_names, feat_vals, shap_vals),
            key=lambda x: abs(x[2]),
            reverse=True,
        )
        return [
            {
                "feature": feat,
                "value"  : round(float(val), 4),
                "impact" : round(float(imp), 4),
            }
            for feat, val, imp in ranked[:top_n]
        ]
    except Exception as e:
        logger.warning("SHAP failed: {} — returning empty explanation", str(e))
        return []


def _combine_scores(xgb_prob: float, recon_error: float) -> float:
    """
    Combine XGBoost (70%) and Autoencoder (30%) into one risk score.

    Why 70/30?
    XGBoost is precise on known fraud patterns.
    Autoencoder catches novel unknown fraud.
    Together they cover each other's blind spots.

    Args:
        xgb_prob    : XGBoost fraud probability (0-1)
        recon_error : Autoencoder reconstruction error (0 to infinity)

    Returns:
        combined risk score (0-1)
    """
    threshold = registry.recon_error_threshold
    ae_score  = min(recon_error / (threshold + 1e-8), 1.0)
    combined  = 0.70 * xgb_prob + 0.30 * ae_score
    return max(0.0, min(1.0, combined))


def _determine_verdict(
    risk_score: float,
) -> tuple[RiskVerdict, ChallengeType]:
    """
    Convert combined risk score into verdict and challenge type.

    < HOLD threshold  → APPROVE, no challenge
    HOLD to DENY      → HOLD, challenge escalates with score
    >= DENY threshold → DENY, blocked immediately

    Args:
        risk_score: combined risk score 0-1

    Returns:
        (RiskVerdict, ChallengeType)
    """
    hold_t = registry.hold_threshold
    deny_t = registry.deny_threshold

    if risk_score >= deny_t:
        return RiskVerdict.DENY, ChallengeType.NONE

    if risk_score >= hold_t:
        mid = (hold_t + deny_t) / 2
        if risk_score >= mid + (deny_t - mid) / 2:
            challenge = ChallengeType.BEHAVIOURAL
        elif risk_score >= mid:
            challenge = ChallengeType.BIOMETRIC
        else:
            challenge = ChallengeType.TAP_CONFIRM
        return RiskVerdict.HOLD, challenge

    return RiskVerdict.APPROVE, ChallengeType.NONE


def should_fast_approve(tx: IncomingTransaction) -> bool:
    """
    PAYMENT, DEBIT, CASH_IN never have fraud (Notebook 01 finding).
    Skip all ML inference and approve instantly — saves ~16ms.

    Args:
        tx: validated incoming transaction

    Returns:
        True if we can approve without running any models
    """
    fraud_relevant = {TransactionType.TRANSFER, TransactionType.CASH_OUT}
    return tx.transaction_type not in fraud_relevant


# ── Main inference entry point ─────────────────────────────────────────────

def run_inference(tx: IncomingTransaction) -> InferenceResult:
    """
    Full hot path inference for a single transaction.
    Must complete in under 30ms.

    Steps:
        1. Build 16 features from the transaction  (~1ms)
        2. XGBoost inference                       (~3ms)
        3. Autoencoder inference                   (~5ms)
        4. SHAP explanation                        (~8ms)
        5. Combine scores + determine verdict      (~0ms)
        Total:                                    ~17ms

    Args:
        tx: validated IncomingTransaction from the API layer

    Returns:
        InferenceResult with verdict, scores, explanation, and latency
    """
    t_start = time.perf_counter()

    # Step 1: Build features
    features: EngineeredFeatures = build_features(tx)

    # ─────────────────────────────────────────────
    # Feature Enrichment Layer
    # ─────────────────────────────────────────────

    recipient_tx_count = enricher.get_recipient_tx_count(
    tx.recipient_id
    )

    logger.info(
        "Feature enrichment | recipient={} | tx_count={}",
        tx.recipient_id,
        recipient_tx_count,
    )

# Override placeholder value from encoders.py
    features.recipient_tx_count = recipient_tx_count    

    logger.info(
        "Enriched feature applied | recipient_tx_count={}",
        features.recipient_tx_count,
    )

    features.dest_was_empty = (
        1 if recipient_tx_count == 0 else 0
    )

    logger.info(
        "Derived feature | dest_was_empty={}",
        features.dest_was_empty,
    )
    
    features_array: np.ndarray = np.array(
        features.to_numpy_array(),
        dtype=np.float32
    ).reshape(1, -1)

    # Step 2: XGBoost
    xgb_prob = _run_xgboost(features_array)

    # Step 3: Autoencoder
    recon_error = _run_autoencoder(features_array)

    # Step 4: SHAP (Skipped on hot-path for latency optimization; calculated in background)
    shap_features = []

    # Step 5: Combine and decide
    combined_score     = _combine_scores(xgb_prob, recon_error)
    verdict, challenge = _determine_verdict(combined_score)

    latency_ms = (time.perf_counter() - t_start) * 1000

    logger.info(
        "Inference | txn={} | verdict={} | xgb={:.4f} | "
        "ae={:.6f} | combined={:.4f} | latency={:.2f}ms",
        str(tx.transaction_id),
        verdict.value,
        xgb_prob,
        recon_error,
        combined_score,
        latency_ms,
    )

    if latency_ms > 30:
        logger.warning(
            "SLA BREACH: {:.2f}ms exceeded 30ms budget | txn={}",
            latency_ms,
            str(tx.transaction_id),
        )

    return InferenceResult(
        transaction_id          = tx.transaction_id,
        verdict                 = verdict,
        challenge_type          = challenge,
        xgb_fraud_prob          = round(xgb_prob, 4),
        autoencoder_recon_error = round(recon_error, 6),
        combined_risk_score     = round(combined_score, 4),
        shap_top_features       = shap_features,
        inference_latency_ms    = round(latency_ms, 2),
    )
