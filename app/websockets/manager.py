"""
app/websocket_manager.py
─────────────────────────
WebSocket Connection Manager for the live dashboard.

WHY WebSockets instead of regular HTTP?
Regular HTTP: client asks → server responds → connection closes.
WebSocket:    connection stays open → server pushes whenever it wants.

Analysts see fraud alerts the INSTANT they happen.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket
from loguru import logger


class ConnectionManager:
    """Manages all active WebSocket connections to the dashboard."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("Dashboard connected | total_clients={}", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("Dashboard disconnected | total_clients={}", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to ALL connected dashboard clients."""
        if not self.active_connections:
            return
        payload = json.dumps(message, default=str)
        dead    = []
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    async def send_alert(
        self,
        verdict        : str,
        transaction_id : str,
        amount         : float,
        account_id     : str,
        risk_score     : float,
        shap_features  : list,
        latency_ms     : float,
        challenge_type : str = "NONE",
        recipient_id   : str = "",
    ) -> None:
        """Send a formatted fraud alert to all connected dashboards."""
        await self.broadcast({
            "type"           : "FRAUD_ALERT",
            "timestamp"      : datetime.now(timezone.utc).isoformat(),
            "verdict"        : verdict,
            "transaction_id" : transaction_id,
            "amount"         : amount,
            "account_id"     : account_id,
            "recipient_id"   : recipient_id,
            "risk_score"     : risk_score,
            "shap_features"  : shap_features,
            "latency_ms"     : latency_ms,
            "challenge_type" : challenge_type,
        })

    async def send_system_status(
        self,
        models_loaded  : bool,
        hold_threshold : float,
        deny_threshold : float,
    ) -> None:
        """Send system health update to all dashboards."""
        await self.broadcast({
            "type"           : "SYSTEM_STATUS",
            "timestamp"      : datetime.now(timezone.utc).isoformat(),
            "models_loaded"  : models_loaded,
            "hold_threshold" : hold_threshold,
            "deny_threshold" : deny_threshold,
            "active_clients" : len(self.active_connections),
        })


# Global singleton — imported by main.py
manager = ConnectionManager()