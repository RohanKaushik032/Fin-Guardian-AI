"""
workers/explanation_worker.py
───────────────────────────────
Fin-Guardian AI — OpenAI Explanation Worker

Subscribes to 'transactions.hold', calls OpenAI to generate plain-English
explanations for HOLD or DENY transactions, and caches them in Redis.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
import redis.asyncio as aioredis
from loguru import logger

from app.core.settings import settings

# ── Logging ───────────────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format=(
        '{{"time":"{time:YYYY-MM-DDTHH:mm:ss.SSS}Z",'
        '"level":"{level}",'
        '"service":"explanation_worker",'
        '"message":"{message}"}}'
    ),
    colorize=False,
)


class ExplanationWorker:
    """
    Subscribes to transactions.hold, gets the feature contributions and risk scores,
    and calls OpenAI to write an analyst summary and a compliance-grade explanation.
    """

    def __init__(self):
        self.redis_client = None
        self.openai_available = bool(settings.OPENAI_API_KEY)
        if self.openai_available:
            try:
                from openai import AsyncOpenAI
                self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            except ImportError:
                logger.error("openai library not installed. Run: pip install openai")
                self.openai_available = False

    async def connect_redis(self) -> None:
        try:
            self.redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await self.redis_client.ping()
            logger.info("Connected to Redis at {}", settings.REDIS_URL)
        except Exception as e:
            logger.error("Redis connection failed: {}", str(e))
            self.redis_client = None

    def translate_feature_name(self, name: str) -> str:
        """Translates machine feature names into plain English."""
        mapping = {
            "amount_to_balance_ratio": "Transaction consumes a large fraction of the available balance.",
            "is_new_recipient": "First-time payment to this recipient.",
            "sender_zeroed": "The transaction will completely drain the sender's account balance.",
            "has_device_id": "Device fingerprint is valid and recognized.",
            "has_location": "GPS coordinates are present.",
            "recipient_seen_before": "The sender has paid this recipient before.",
            "tx_count_1h": "High velocity: multiple transactions sent within the last hour.",
            "tx_count_24h": "High frequency: multiple transactions sent within the last day.",
            "amount_log": "High transaction value.",
            "type_encoded": "Electronic wire transfer (higher risk transaction type)."
        }
        return mapping.get(name, f"Feature '{name}' contributed to the risk.")

    async def generate_explanation(self, transaction: dict, inference: dict) -> dict:
        """
        Calls OpenAI to summarize findings and present them in a clean format.
        """
        txn_id = transaction.get("transaction_id", "unknown")
        amount = transaction.get("amount", 0.0)
        verdict = inference.get("verdict", "HOLD")
        risk_score = inference.get("combined_risk_score", 0.5)

        # Build list of top features if available
        shap_features = inference.get("shap_top_features", [])
        reasons = []
        for feat in shap_features[:3]:
            impact = feat.get("impact", 0.0)
            name = feat.get("feature", "")
            if abs(impact) > 0.02:
                reasons.append(self.translate_feature_name(name))

        if not reasons:
            reasons.append("Suspicious transaction velocity or novel behavioral anomaly.")

        # Default fallback explanation in case OpenAI key is missing
        fallback_narrative = (
            f"Transaction evaluated with verdict {verdict} due to high-risk profile. "
            f"Key factors include: {'; '.join(reasons)}."
        )

        explanation = {
            "transaction_id": txn_id,
            "analyst_summary": fallback_narrative,
            "confidence_score": int(risk_score * 100),
            "reasons": reasons,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        if not self.openai_available:
            logger.info("OpenAI API key not set - returning rule-based explanation.")
            return explanation

        # Call OpenAI Chat Completion
        try:
            prompt = (
                f"You are an expert fraud compliance analyst at a major bank. Analyze the following transaction:\n"
                f"Amount: INR {amount:,.2f}\n"
                f"Model Verdict: {verdict}\n"
                f"Combined Risk Score: {risk_score:.2f} (0 to 1 scaling)\n"
                f"Triggered risk indicators:\n"
                + "\n".join(f"- {r}" for r in reasons) +
                f"\n\nWrite a 2-3 sentence executive analyst summary explaining why this was blocked/held "
                f"and give a recommended next step (e.g., identity verification or account freeze)."
            )

            response = await self.openai_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a professional banking fraud auditor. Be concise, direct, and formal."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.3
            )

            summary = response.choices[0].message.content.strip()
            explanation["analyst_summary"] = summary
            logger.info("OpenAI explanation generated successfully for txn={}", txn_id)

        except Exception as e:
            logger.error("Failed to call OpenAI: {}", str(e))

        return explanation

    async def run(self) -> None:
        await self.connect_redis()

        logger.info("Starting Explanation Worker — listening on 'transactions.hold'...")

        try:
            from aiokafka import AIOKafkaConsumer

            consumer = AIOKafkaConsumer(
                "transactions.hold",
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id="explanation_workers",
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )

            await consumer.start()
            logger.info("Explanation Kafka consumer started")

            try:
                async for message in consumer:
                    event_data = message.value
                    transaction = event_data.get("transaction", {})
                    inference = event_data.get("inference_result", {})
                    txn_id = transaction.get("transaction_id", "unknown")

                    logger.info("Generating AI explanation for HOLD txn={}", txn_id)
                    explanation = await self.generate_explanation(transaction, inference)

                    # Save to Redis with 7 days TTL (604800 seconds)
                    if self.redis_client:
                        key = f"explanation:{txn_id}"
                        await self.redis_client.setex(key, 604800, json.dumps(explanation))
                        logger.info("AI explanation saved to Redis | key={}", key)

                        # Broadcast via WebSocket client manager if active
                        # (We can broadcast this event back so the dashboard updates with explanation)
                        payload = json.dumps({
                            "type": "EXPLANATION_COMPLETE",
                            "transaction_id": txn_id,
                            "explanation": explanation
                        })
                        # Publish payload to a Redis channel for the dashboard to receive
                        await self.redis_client.publish("dashboard_alerts", payload)

                    await consumer.commit()

            finally:
                await consumer.stop()

        except ImportError:
            logger.error("aiokafka not installed.")
        except Exception as e:
            logger.error("Explanation worker error: {}", str(e))


if __name__ == "__main__":
    logger.info("Explanation Worker starting...")
    worker = ExplanationWorker()
    asyncio.run(worker.run())
