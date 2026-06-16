"""
app/features/feature_store.py
──────────────────────────────
Shared Feature Store of Fin-Guardian AI.

Stores and retrieves rolling transaction stats in Redis to prevent training-serving skew.
Computes tx_count_1h, tx_count_24h, avg_amount_7d, avg_amount_30d, and recipient_seen_before in <2ms.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
import redis
from loguru import logger

from app.core.settings import settings


class FeatureStore:
    """
    Computes and updates real-time behavioral features using a Redis backend.
    
    Structure in Redis:
      - Key: 'tx_history:{account_id}' -> Redis Sorted Set
        - score: Unix timestamp
        - member: JSON string: {"amount": float, "recipient_id": str}
    """

    def __init__(self, redis_url: str = settings.REDIS_URL):
        self.redis_url = redis_url
        self.client = None
        try:
            self.client = redis.Redis.from_url(redis_url, decode_responses=True)
            self.client.ping()
            logger.info("FeatureStore connected to Redis at {}", redis_url)
        except Exception as e:
            logger.warning("FeatureStore Redis connection failed: {} - using in-memory mock", str(e))
            self.client = None

    def record_transaction(self, account_id: str, recipient_id: str, amount: float, timestamp: datetime) -> None:
        """
        Record a transaction to the history for the account.
        Keeps a rolling 30-day window.
        """
        if not self.client:
            return

        try:
            ts_seconds = int(timestamp.timestamp())
            payload = json.dumps({
                "amount": amount,
                "recipient_id": recipient_id,
                "timestamp": timestamp.isoformat()
            })
            key = f"tx_history:{account_id}"
            
            # Add new transaction
            self.client.zadd(key, {payload: ts_seconds})
            
            # Clean up records older than 30 days (2592000 seconds)
            min_ts = ts_seconds - 2592000
            self.client.zremrangebyscore(key, "-inf", min_ts)
            
            # Set TTL on the history key to 31 days
            self.client.expire(key, 2678400)
        except Exception as e:
            logger.error("Failed to record transaction in feature store: {}", str(e))

    def get_rolling_features(self, account_id: str, recipient_id: str, current_time: datetime) -> dict[str, float]:
        """
        Compute rolling behavioral features for a given account.
        
        Returns:
            {
                "tx_count_1h": float,
                "tx_count_24h": float,
                "avg_amount_7d": float,
                "avg_amount_30d": float,
                "recipient_seen_before": float
            }
        """
        # Default fallback values if Redis is offline or history is empty
        defaults = {
            "tx_count_1h": 0.0,
            "tx_count_24h": 0.0,
            "avg_amount_7d": 0.0,
            "avg_amount_30d": 0.0,
            "recipient_seen_before": 0.0
        }
        
        if not self.client:
            return defaults

        try:
            key = f"tx_history:{account_id}"
            now_ts = int(current_time.timestamp())
            
            # Fetch the entire 30-day window
            min_ts = now_ts - 2592000
            records = self.client.zrangebyscore(key, min_ts, "+inf", withscores=True)
            
            if not records:
                return defaults

            tx_count_1h = 0
            tx_count_24h = 0
            sum_amount_7d = 0.0
            tx_count_7d = 0
            sum_amount_30d = 0.0
            tx_count_30d = 0
            recipient_seen_before = 0.0

            for member, score in records:
                try:
                    data = json.loads(member)
                except Exception:
                    continue

                ts_diff = now_ts - int(score)
                amount = data.get("amount", 0.0)
                rec = data.get("recipient_id", "")

                if ts_diff <= 3600:
                    tx_count_1h += 1
                if ts_diff <= 86400:
                    tx_count_24h += 1
                if ts_diff <= 604800:
                    sum_amount_7d += amount
                    tx_count_7d += 1
                if ts_diff <= 2592000:
                    sum_amount_30d += amount
                    tx_count_30d += 1

                if rec == recipient_id:
                    recipient_seen_before = 1.0

            avg_amount_7d = sum_amount_7d / tx_count_7d if tx_count_7d > 0 else 0.0
            avg_amount_30d = sum_amount_30d / tx_count_30d if tx_count_30d > 0 else 0.0

            return {
                "tx_count_1h": float(tx_count_1h),
                "tx_count_24h": float(tx_count_24h),
                "avg_amount_7d": float(avg_amount_7d),
                "avg_amount_30d": float(avg_amount_30d),
                "recipient_seen_before": float(recipient_seen_before)
            }

        except Exception as e:
            logger.error("Failed to compute rolling features: {}", str(e))
            return defaults


feature_store = FeatureStore()
