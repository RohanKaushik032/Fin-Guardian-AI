from neo4j import GraphDatabase
from loguru import logger

from app.core.settings import settings


class FeatureEnricher:

    def __init__(self):
        try:
            self.driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(
                    settings.NEO4J_USER,
                    settings.NEO4J_PASSWORD,
                ),
            )
        except Exception as e:
            logger.error("Neo4j connection failed: {}", str(e))
            # pyrefly: ignore [bad-assignment]
            self.driver = None

    def get_recipient_tx_count(self, recipient_id: str) -> int:

        if not self.driver:
            return 0

        query = """
        MATCH ()-[t:TRANSFERRED_TO]->(r:Account)
        WHERE r.account_id = $recipient_id
        RETURN count(t) AS tx_count
        """

        try:
            with self.driver.session() as session:
                result = session.run(
                    query,
                    recipient_id=recipient_id,
                )

                record = result.single()

                if record:
                    return int(record["tx_count"])

        except Exception as e:
            logger.warning(
                "Recipient count lookup failed: {}",
                str(e)
            )

        return 0


enricher = FeatureEnricher()
