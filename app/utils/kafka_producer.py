"""Kafka message producer for HOLD events."""

import json
from loguru import logger
from typing import Optional
from datetime import datetime


def publish_hold_event(
    transaction_id: str,
    # pyrefly: ignore [unknown-name]
    request: "TransactionRequest",
    fraud_score: float,
    investigation_id: str
) -> None:
    """
    Publish a HOLD event to Kafka for asynchronous investigation.
    
    This function is fire-and-forget:
    - Does NOT block the transaction API response
    - Investigation happens in background via workers
    - Gracefully handles Kafka failures
    """
    try:
        from aiokafka import AIOKafkaProducer
        import asyncio
        
        async def _publish():
            try:
                producer = AIOKafkaProducer(bootstrap_servers="localhost:29092")
                await producer.start()
                
                event = {
                    "transaction_id": transaction_id,
                    "account_id": request.account_id,
                    "recipient_id": request.recipient_id,
                    "amount": request.amount,
                    "fraud_score": fraud_score,
                    "investigation_id": investigation_id,
                    # pyrefly: ignore [deprecated]
                    "timestamp": datetime.utcnow().isoformat(),
                    "features": {
                        "is_new_recipient": request.is_new_recipient,
                        "account_age_days": request.account_age_days,
                        "account_balance_before": request.account_balance_before,
                        "sender_tx_count": request.sender_tx_count
                    }
                }
                
                payload = json.dumps(event).encode("utf-8")
                await producer.send_and_wait("transactions.hold", payload)
                
                logger.info(f"HOLD event published to Kafka | txn={transaction_id}")
                
                await producer.stop()
            
            except Exception as e:
                logger.error(f"Failed to publish HOLD event: {e}")
        
        # Schedule async publish (fire-and-forget)
        asyncio.create_task(_publish())
    
    except ImportError:
        logger.warning("aiokafka not installed — Kafka publishing disabled")
    except Exception as e:
        logger.error(f"Error setting up Kafka producer: {e}")
