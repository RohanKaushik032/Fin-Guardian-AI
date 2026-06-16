"""
app/main.py
───────────
Fin-Guardian AI — FastAPI Ingestion Gateway
"""

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from app.core.settings import settings
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.auth import require_api_key
from app.inference import registry, run_inference, should_fast_approve
from app.schemas.transaction import (
    HoldEvent,
    IncomingTransaction,
    InferenceResult,
    RiskVerdict,
    TransactionType,
)
from app.core.kafka_service import (
    startup_kafka,
    shutdown_kafka,
    get_producer,
)

import asyncio

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from app.websockets.manager import manager


# ── Logging setup ─────────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format=(
        '{{"time":"{time:YYYY-MM-DDTHH:mm:ss.SSS}Z",'
        '"level":"{level}",'
        '"service":"gateway",'
        '"message":"{message}"}}'
    ),
    colorize=False,
)


# ── Kafka publisher ────────────────────────────────────────────────────────

async def publish_hold_event(event: HoldEvent) -> None:
    """
    Publish HOLD event to Kafka for async deep investigation.
    Degrades gracefully if Kafka is not running.
    """
    try:
        producer = get_producer()

        if producer is None:
            logger.warning(
                "Kafka producer unavailable | txn={}",
                str(event.transaction.transaction_id)
            )
            return

        payload = event.model_dump_json().encode("utf-8")

        await producer.send_and_wait(
            "transactions.hold",
            payload
        )

        logger.info(
            "HOLD event published to Kafka | txn={}",
            str(event.transaction.transaction_id)
        )

    except ImportError:
        logger.warning("aiokafka not installed — HOLD event logged only | txn={}",
                       str(event.transaction.transaction_id))

    except Exception as e:
        logger.error("Kafka publish failed: {} | txn={} | investigation skipped",
                     str(e), str(event.transaction.transaction_id))


# ── Lifespan ──────────────────────────────────────────────────────────────

async def redis_pubsub_listener():
    import redis.asyncio as aioredis
    import json
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe("dashboard_alerts")
        logger.info("Subscribed to Redis pubsub channel 'dashboard_alerts'")
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                try:
                    payload = json.loads(message["data"])
                    await manager.broadcast(payload)
                except Exception as val_e:
                    logger.error("Failed to parse pubsub message payload: {}", str(val_e))
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error("Redis pubsub listener failed: {}", str(e))

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Fin-Guardian AI Gateway starting up...")

    try:
        registry.load_all(artifacts_dir="artifacts")
        await startup_kafka()
        asyncio.create_task(redis_pubsub_listener())
        logger.info("Gateway ready — all models loaded")

    except Exception as e:
        logger.error("FATAL: Failed to start gateway: {}", str(e))
        raise RuntimeError(f"Gateway startup failed: {e}")

    yield

    await shutdown_kafka()
    logger.info("Fin-Guardian AI Gateway shutting down...")

# ── Rate limiter ──────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT_GLOBAL])

# ── App ───────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "Fin-Guardian AI",
    description = "Autonomous fraud detection. Layer 1 hot path: XGBoost + Autoencoder + SHAP.",
    version     = "1.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

# Rate limiter exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ── Request timing middleware ─────────────────────────────────────────────

@app.middleware("http")
async def add_request_timing(request: Request, call_next):
    t0       = time.perf_counter()
    response = await call_next(request)
    elapsed  = (time.perf_counter() - t0) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed:.2f}"
    return response


@app.get("/", tags=["System"])
async def read_root():
    return {"name": "Fin-Guardian AI Gateway", "version": "1.0.0", "status": "running"}


@app.get("/api/v1/transactions/status", tags=["System"])
async def transaction_status():
    return {"service": "transactions-api", "status": "active"}


@app.get("/health", tags=["System"])
async def health_check():
    # Check Redis
    redis_healthy = False
    try:
        import redis
        r = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=1)
        r.ping()
        redis_healthy = True
    except Exception:
        pass

    # Check Neo4j
    neo4j_healthy = False
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            connection_timeout=1
        )
        driver.verify_connectivity()
        driver.close()
        neo4j_healthy = True
    except Exception:
        pass

    # Check Kafka
    kafka_healthy = False
    try:
        producer_instance = get_producer()
        if producer_instance is not None:
            kafka_healthy = True
    except Exception:
        pass

    all_healthy = registry.is_loaded and redis_healthy and neo4j_healthy and kafka_healthy

    return {
        "status": "healthy" if all_healthy else "degraded",
        "models_loaded": registry.is_loaded,
        "redis_connected": redis_healthy,
        "neo4j_connected": neo4j_healthy,
        "kafka_connected": kafka_healthy,
        "service": "fin-guardian-gateway",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dashboard_clients": len(manager.active_connections),
        "thresholds": {
            "hold": registry.hold_threshold,
            "deny": registry.deny_threshold,
        } if registry.is_loaded else None,
    }


@app.websocket("/api/v1/ws/alerts")
async def websocket_alerts(websocket: WebSocket):

    await manager.connect(websocket)
    if registry.is_loaded:
        await manager.send_system_status(
            models_loaded=True,
            hold_threshold=registry.hold_threshold,
            deny_threshold=registry.deny_threshold,
        )

    try:
        while True:

            try:
                await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )

            except asyncio.TimeoutError:

                 await websocket.send_text(
                       f'{{"type":"HEARTBEAT","timestamp":"{datetime.now(timezone.utc).isoformat()}"}}'
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)




# ── Main transaction endpoint ─────────────────────────────────────────────

@app.post(
    "/api/v1/transactions/evaluate",
    response_model = InferenceResult,
    status_code    = status.HTTP_200_OK,
    tags           = ["Fraud Detection"],
    summary        = "Evaluate a transaction for fraud risk",
    dependencies   = [Depends(require_api_key)],
)
async def evaluate_transaction(tx: IncomingTransaction) -> InferenceResult:
    """
    Submit a transaction for real-time fraud evaluation.
    Returns APPROVE, HOLD, or DENY with SHAP explanation in under 30ms.
    """
    if not registry.is_loaded:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Models not loaded — service is starting up.",
        )

    logger.info(
        "Transaction received | txn={} | type={} | amount={} | account={}",
        str(tx.transaction_id),
        tx.transaction_type.value,
        tx.amount,
        tx.account_id,
    )

    # Fast-approve non-fraud-relevant types (PAYMENT, DEBIT, CASH_IN)
    if should_fast_approve(tx):
        logger.info("Fast-approved | txn={} | type={}",
                    str(tx.transaction_id), tx.transaction_type.value)
        fast_result = InferenceResult(
            transaction_id          = tx.transaction_id,
            verdict                 = RiskVerdict.APPROVE,
            xgb_fraud_prob          = 0.0,
            autoencoder_recon_error = 0.0,
            combined_risk_score     = 0.0,
            shap_top_features       = [],
            inference_latency_ms    = 0.1,
        )
        # Broadcast APPROVE to dashboard so the timeline shows all transactions
        asyncio.create_task(
            manager.send_alert(
                verdict="APPROVE",
                transaction_id=str(tx.transaction_id),
                amount=tx.amount,
                account_id=tx.account_id,
                risk_score=0.0,
                shap_features=[],
                latency_ms=0.1,
                challenge_type="NONE",
                recipient_id=tx.recipient_id,
            )
        )
        return fast_result

    # Full ML inference for TRANSFER and CASH_OUT
    result = run_inference(tx)

    # Broadcast verdict to dashboard for ALL outcomes
    asyncio.create_task(
        manager.send_alert(
            verdict=result.verdict.value,
            transaction_id=str(tx.transaction_id),
            amount=tx.amount,
            account_id=tx.account_id,
            risk_score=result.combined_risk_score,
            shap_features=result.shap_top_features,
            latency_ms=result.inference_latency_ms,
            challenge_type=result.challenge_type.value,
            recipient_id=tx.recipient_id,
        )
    )

    if result.verdict in (
        RiskVerdict.HOLD,
        RiskVerdict.DENY,
    ):
        from app.utils.encoders import build_features
        hold_event = HoldEvent(
            transaction      = tx,
            features         = build_features(tx),
            inference_result = result,
        )
        asyncio.create_task(publish_hold_event(hold_event))
        logger.info("{} verdict | txn={} | challenge={}",
                    result.verdict.value, str(tx.transaction_id), result.challenge_type.value)

        # Launch AI Detective investigation in background (Layer 3)
        asyncio.create_task(
            _run_detective_and_push(
                tx=tx,
                result=result,
            )
        )

    return result


async def _run_detective_and_push(tx: IncomingTransaction, result: InferenceResult) -> None:
    """
    Background task: run the LangGraph AI Detective investigation,
    calculate SHAP features, generate the explanation, and push all
    results to the dashboard WebSocket and Redis cache.
    """
    import json as _json
    import redis.asyncio as aioredis
    import numpy as np
    from app.inference import _run_shap
    from app.utils.encoders import build_features
    from app.services.feature_enrichment import enricher

    transaction_id = str(tx.transaction_id)
    
    # 1. Compute SHAP features in background since they were skipped on the hot path
    try:
        features = build_features(tx)
        recipient_tx_count = enricher.get_recipient_tx_count(tx.recipient_id)
        features.recipient_tx_count = recipient_tx_count
        features.dest_was_empty = 1 if recipient_tx_count == 0 else 0

        features_array = np.array(
            features.to_numpy_array(),
            dtype=np.float32
        ).reshape(1, -1)

        shap_features = _run_shap(features_array)
    except Exception as shap_err:
        logger.error("SHAP background computation failed: {}", str(shap_err))
        shap_features = []

    # 2. Generate and broadcast explanation
    try:
        from workers.explanation_worker import ExplanationWorker
        worker = ExplanationWorker()
        tx_dict = {
            "transaction_id": transaction_id,
            "amount": tx.amount,
            "account_id": tx.account_id,
            "recipient_id": tx.recipient_id,
            "account_age_days": tx.account_age_days,
            "is_new_recipient": tx.is_new_recipient,
            "sender_tx_count": tx.sender_tx_count,
            "timestamp": tx.timestamp.isoformat() if hasattr(tx.timestamp, "isoformat") else str(tx.timestamp),
            "device_id": tx.device_id,
            "ip_address": tx.ip_address,
            "latitude": tx.latitude,
            "longitude": tx.longitude,
        }
        result_dict = {
            "verdict": result.verdict.value,
            "combined_risk_score": result.combined_risk_score,
            "shap_top_features": shap_features,
        }
        explanation = await worker.generate_explanation(tx_dict, result_dict)

        # Cache explanation in Redis for REST polling fallback
        try:
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.setex(
                f"explanation:{transaction_id}",
                604800,  # TTL: 7 days
                _json.dumps(explanation),
            )
            await r.aclose()
        except Exception as redis_e:
            logger.warning("Could not save explanation to Redis: {}", str(redis_e))

        # Push explanation complete event
        await manager.broadcast({
            "type": "EXPLANATION_COMPLETE",
            "transaction_id": transaction_id,
            "explanation": explanation,
        })
        logger.info("AI explanation generated and pushed for tx={}", transaction_id)
    except Exception as exp_err:
        logger.error("Explanation background task failed: {}", str(exp_err))

    # 3. Run full LangGraph AI Detective investigation
    try:
        from app.agents.fraud_detective import run_investigation

        investigation = await run_investigation(
            transaction_id    = transaction_id,
            account_id        = tx.account_id,
            recipient_id      = tx.recipient_id,
            amount            = tx.amount,
            account_age_days  = tx.account_age_days,
            is_new_recipient  = tx.is_new_recipient,
            sender_tx_count   = tx.sender_tx_count,
            hour_of_day       = tx.timestamp.hour,
            ip_address        = tx.ip_address,
            device_id         = tx.device_id,
            has_gps           = tx.latitude is not None,
            ml_risk_score     = result.combined_risk_score,
            ml_verdict        = result.verdict.value,
            shap_top_features = shap_features,
        )

        inv_payload = {
            "type": "INVESTIGATION_COMPLETE",
            "transaction_id": transaction_id,
            "forensic_report": investigation["forensic_report"],
            "final_confidence": investigation["final_confidence"],
            "graph_risk": investigation["graph_report"].get("risk_level", "UNKNOWN"),
            "device_risk": investigation["device_report"].get("risk_level", "UNKNOWN"),
            "ip_vpn": investigation["ip_report"].get("is_vpn_proxy", False),
            "investigation_duration_ms": investigation["investigation_duration_ms"],
            "shap_features": shap_features,
        }

        # Save to Redis for REST polling fallback
        try:
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.setex(
                f"forensic:{transaction_id}",
                3600,  # TTL: 1 hour
                _json.dumps(inv_payload),
            )
            await r.aclose()
        except Exception as redis_e:
            logger.warning("Could not save forensic to Redis: {}", str(redis_e))

        # Push forensic report to dashboard via WebSocket
        await manager.broadcast(inv_payload)

        logger.info(
            "Detective pushed to dashboard | tx={} | confidence={} | duration={}ms",
            transaction_id,
            investigation["final_confidence"],
            investigation["investigation_duration_ms"],
        )

    except Exception as e:
        logger.error("Detective background task failed for tx={}: {}", transaction_id, str(e))
        # Push a minimal failure report so the UI doesn't stay stuck on SCANNING
        fallback_payload = {
            "type": "INVESTIGATION_COMPLETE",
            "transaction_id": transaction_id,
            "forensic_report": f"Investigation encountered an error: {str(e)}. ML verdict ({result.verdict.value}) stands based on model scores.",
            "final_confidence": "LOW",
            "graph_risk": "UNKNOWN",
            "device_risk": "UNKNOWN",
            "ip_vpn": False,
            "investigation_duration_ms": 0.0,
            "shap_features": shap_features,
        }
        await manager.broadcast(fallback_payload)



# ── Midnight Ghost test endpoint ──────────────────────────────────────────

@app.get(
    "/api/v1/transactions/test-midnight-ghost",
    response_model = InferenceResult,
    tags           = ["Development"],
    summary        = "Test with the Midnight Ghost scenario",
)
async def test_midnight_ghost() -> InferenceResult:
    """
    Tests the Midnight Ghost scenario:
    Priya's account — ₹92,000 TRANSFER at 11:45 PM to a new recipient.
    Expected result: HOLD or DENY.
    """
    if not registry.is_loaded:
        raise HTTPException(status_code=503, detail="Models not loaded.")

    # ── FIXED: use a hardcoded past date so the timestamp validator
    # never rejects it as "in the future".
    # January 15, 2026 23:45 UTC is always in the past.
    midnight_ghost = IncomingTransaction(
        account_id             = "C_PRIYA_STUDENT_001",
        recipient_id           = "C_UNKNOWN_RECIPIENT_999",
        amount                 = 83148.0,
        transaction_type       = TransactionType.TRANSFER,
        timestamp              = datetime(2026, 1, 15, 23, 45, 0, tzinfo=timezone.utc),
        device_id              = None,      # No device ID — suspicious
        ip_address             = None,
        latitude               = None,      # No GPS — Midnight Ghost signal
        longitude              = None,
        account_age_days       = 180,       # 6-month-old account
        account_balance_before = 83148.0,   # Drains account completely to 0
        is_new_recipient       = True,      # Brand new recipient
        sender_tx_count        = 1,         # First sender transaction
    )

    result = run_inference(midnight_ghost)

    if result.verdict in (
        RiskVerdict.HOLD,
        RiskVerdict.DENY,
    ):
        asyncio.create_task(
            manager.send_alert(
                verdict=result.verdict.value,
                transaction_id=str(midnight_ghost.transaction_id),
                amount=midnight_ghost.amount,
                account_id=midnight_ghost.account_id,
                risk_score=result.combined_risk_score,
                shap_features=result.shap_top_features,
                latency_ms=result.inference_latency_ms,
                challenge_type=result.challenge_type.value,
                recipient_id=midnight_ghost.recipient_id,
            )
        )

        from app.utils.encoders import build_features
        hold_event = HoldEvent(
            transaction      = midnight_ghost,
            features         = build_features(midnight_ghost),
            inference_result = result,
        )
        asyncio.create_task(publish_hold_event(hold_event))
        logger.info("{} verdict | txn={} | challenge={}",
                    result.verdict.value, str(midnight_ghost.transaction_id), result.challenge_type.value)

        # Launch AI Detective investigation in background (Layer 3)
        asyncio.create_task(
            _run_detective_and_push(
                tx=midnight_ghost,
                result=result,
            )
        )

    logger.info(
        "Midnight Ghost test | verdict={} | risk={:.4f}",
        result.verdict.value,
        result.combined_risk_score
    )

    return result


# ── REST API: Fetch investigation/explanation from Redis ──────────────────

@app.get(
    "/api/v1/investigations/{transaction_id}",
    tags=["Investigations"],
    summary="Fetch investigation and explanation results from Redis",
)
async def get_investigation(transaction_id: str):
    """
    Fetch the cached investigation and explanation for a transaction from Redis.
    This is the dashboard's fallback when a WebSocket event was missed.
    """
    import redis.asyncio as aioredis
    import json as _json

    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

        inv_raw = await r.get(f"investigation:{transaction_id}")
        exp_raw = await r.get(f"explanation:{transaction_id}")
        forensic_raw = await r.get(f"forensic:{transaction_id}")

        investigation = _json.loads(inv_raw) if inv_raw else None
        explanation = _json.loads(exp_raw) if exp_raw else None
        forensic = _json.loads(forensic_raw) if forensic_raw else None

        await r.aclose()

        return {
            "transaction_id": transaction_id,
            "investigation": investigation,
            "explanation": explanation,
            "forensic": forensic,
            "found": bool(investigation or explanation or forensic),
        }
    except Exception as e:
        logger.error("Failed to fetch investigation from Redis: {}", str(e))
        return {
            "transaction_id": transaction_id,
            "investigation": None,
            "explanation": None,
            "forensic": None,
            "found": False,
        }


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():

    try:
        with open("dashboard/index.html", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    except FileNotFoundError:

        return HTMLResponse(
            content="<h2>Dashboard file not found</h2>",
            status_code=404
        )
    

# ── Run directly ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)