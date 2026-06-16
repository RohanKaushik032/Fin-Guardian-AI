"""
app/dashboard.py
────────────────
Fin-Guardian AI — Live Dashboard WebSocket Stream

Serves a real-time HTML dashboard that shows:
1. Transactions flowing through the gateway
2. Risk scores and verdicts (APPROVE/HOLD/DENY)
3. Neo4j investigation results
4. Live alerts when fraud is detected
"""

import json
import asyncio
from datetime import datetime, timezone
from typing import Set
from app.core.settings import settings

import redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

router = APIRouter()

# Store active WebSocket connections
active_connections: Set[WebSocket] = set()
redis_client = None


async def get_redis_client():
    """Get or create Redis connection."""
    global redis_client
    if redis_client is None:
        try:
            redis_client = redis.from_url(settings.REDIS_URL)
            redis_client.ping()
            logger.info("Dashboard connected to Redis")
        except Exception as e:
            logger.warning("Dashboard: Redis not available ({})", str(e))
            redis_client = None
    return redis_client


async def broadcast_event(event: dict) -> None:
    """Send event to all connected dashboard clients."""
    if not active_connections:
        return
    
    disconnected = set()
    for connection in active_connections:
        try:
            await connection.send_json(event)
        except Exception as e:
            logger.debug("Failed to send to dashboard client: {}", str(e))
            disconnected.add(connection)
    
    # Clean up disconnected clients
    for conn in disconnected:
        active_connections.discard(conn)


async def stream_redis_events():
    """
    Background task: monitor Redis for new investigation results.
    Broadcasts them to all connected dashboard clients.
    """
    redis_conn = await get_redis_client()
    if not redis_conn:
        return
    
    pubsub = redis_conn.pubsub()
    pubsub.subscribe("investigation:completed")
    
    try:
        for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    # pyrefly: ignore [bad-argument-type]
                    data = json.loads(message["data"])
                    await broadcast_event({
                        "type": "investigation_completed",
                        "data": data,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        logger.error("Redis stream error: {}", str(e))
    finally:
        pubsub.close()


@router.get("/dashboard")
async def get_dashboard():
    """Serve the HTML dashboard."""
    return {
        "message": "Visit http://localhost:8000/dashboard.html to see the live dashboard"
    }


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """
    WebSocket endpoint for real-time dashboard updates.
    
    Clients connect here to receive:
    - Live transaction events
    - Risk scores
    - Investigation results
    - Fraud alerts
    """
    await websocket.accept()
    active_connections.add(websocket)
    
    logger.info("Dashboard client connected (total: {})", len(active_connections))
    
    try:
        redis_conn = await get_redis_client()
        
        # Send initial system status
        await websocket.send_json({
            "type": "system_status",
            "redis_connected": redis_conn is not None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Listen for incoming messages (keep connection alive)
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            # Handle dashboard requests
            if msg.get("action") == "get_recent_transactions":
                if redis_conn:
                    # Get last 10 transactions from Redis
                    keys = list(redis_conn.scan_iter("transaction:*"))
                    transactions = []
                    for key in sorted(keys)[-10:]:
                        tx_data = redis_conn.get(key)
                        if tx_data:
                            try:
                                transactions.append(json.loads(tx_data))
                            except json.JSONDecodeError:
                                pass
                    
                    await websocket.send_json({
                        "type": "recent_transactions",
                        "data": transactions,
                        "count": len(transactions)
                    })
            
            elif msg.get("action") == "get_stats":
                if redis_conn:
                    # Get fraud statistics
                    stats = {
                        "total_transactions": len(list(redis_conn.scan_iter("transaction:*"))),
                        "investigations": len(list(redis_conn.scan_iter("investigation:*"))),
                        "fraud_detected": len(list(redis_conn.scan_iter("fraud:*"))),
                    }
                    await websocket.send_json({
                        "type": "stats",
                        "data": stats
                    })
    
    except WebSocketDisconnect:
        active_connections.discard(websocket)
        logger.info("Dashboard client disconnected (total: {})", len(active_connections))
    except Exception as e:
        logger.error("Dashboard WebSocket error: {}", str(e))
        active_connections.discard(websocket)


def register_dashboard_routes(app):
    """Register dashboard routes with the FastAPI app."""
    app.include_router(router)
