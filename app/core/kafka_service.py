"""
app/core/kafka_service.py
Singleton Kafka producer for Fin-Guardian AI
"""

from aiokafka import AIOKafkaProducer
from loguru import logger

from app.core.settings import settings

# Global producer instance
producer: AIOKafkaProducer | None = None


async def startup_kafka() -> None:
    """
    Create and start Kafka producer once during application startup.
    """
    global producer

    if producer is None:
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
        )

        await producer.start()
        logger.info("Kafka producer started")


async def shutdown_kafka() -> None:
    """
    Gracefully close Kafka producer.
    """
    global producer

    if producer is not None:
        await producer.stop()
        producer = None
        logger.info("Kafka producer stopped")


def get_producer() -> AIOKafkaProducer | None:
    """
    Return the singleton producer instance.
    """
    return producer