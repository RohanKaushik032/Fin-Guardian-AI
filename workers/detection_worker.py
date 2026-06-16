"""
workers/detection_worker.py
────────────────────────────
Fin-Guardian AI — Async Detection Worker (Layer 2)

This worker runs OUTSIDE the FastAPI gateway, completely independently.
It reads HOLD events from Kafka and runs deep graph investigation.

WHY a separate worker?
The gateway must respond in 30ms. Graph queries take 200-500ms.
If we ran graph queries in the gateway, every HOLD would take 500ms+.
Instead:
  1. Gateway issues HOLD verdict in ~17ms → returns to client
  2. Gateway publishes event to Kafka (takes ~1ms, non-blocking)
  3. THIS WORKER picks up the event from Kafka
  4. Worker runs Neo4j graph analysis (~300ms) — client already got their response
  5. Worker updates the investigation report in Redis

The client never waits for step 3-5. That's the power of async architecture.

ANALOGY (data science):
This is like running a slow model.predict() in a background thread
while the main thread keeps accepting new requests.

HOW TO RUN:
  python workers/detection_worker.py

WHAT IT DOES FOR EACH HOLD EVENT:
  1. Reads the HOLD event from Kafka
  2. Queries Neo4j: is the recipient in a known fraud network?
  3. Queries Neo4j: how many unique senders to this recipient recently?
  4. Queries Neo4j: is this sender connected to other fraud cases?
  5. Computes a graph risk score
  6. Saves investigation report to Redis
  7. Writes new transaction edges to Neo4j graph
  8. Acknowledges the Kafka message (marks it as processed)
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from app.core.settings import settings
from loguru import logger



# ── Logging ───────────────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format=(
        '{{"time":"{time:YYYY-MM-DDTHH:mm:ss.SSS}Z",'
        '"level":"{level}",'
        '"service":"detection_worker",'
        '"message":"{message}"}}'
    ),
    colorize=False,
)


# ── Neo4j connection ──────────────────────────────────────────────────────

class GraphInvestigator:
    """
    Runs deterministic graph queries against Neo4j.

    WHY deterministic?
    Our architecture rule: the LLM (AI agent) decides WHAT to investigate.
    These functions do the actual data retrieval with hard-coded queries.
    No AI guesswork in data access — results are reproducible and auditable.
    """

    def __init__(self, uri: str, user: str, password: str):
        self.uri      = uri
        self.user     = user
        self.password = password
        self.driver   = None

    async def connect(self) -> None:
        """Connect to Neo4j. Called once at worker startup."""
        try:
            from neo4j import AsyncGraphDatabase
            self.driver = AsyncGraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            await self.driver.verify_connectivity()
            logger.info("Connected to Neo4j at {}", self.uri)
        except Exception as e:
            logger.error("Neo4j connection failed: {} — graph queries will be skipped", str(e))
            self.driver = None

    async def close(self) -> None:
        if self.driver:
            await self.driver.close()

    async def get_recipient_risk(self, recipient_id: str) -> dict:
        """
        Query 1: How risky is the recipient account?

        Checks:
        - How many unique senders in last 30 days? (many = mule account)
        - Is the recipient connected to any flagged accounts?
        - Total amount received recently?

        Returns a risk summary dict.
        """
        if not self.driver:
            return {"error": "Neo4j not available", "graph_risk": 0.0}

        query = """
        MATCH (recipient:Account {account_id: $recipient_id})
        OPTIONAL MATCH (sender:Account)-[t:TRANSFERRED_TO]->(recipient)
        WHERE t.timestamp > datetime() - duration({days: 30})
        WITH recipient,
             count(DISTINCT sender) AS unique_senders_30d,
             sum(t.amount)          AS total_received_30d,
             count(t)               AS transaction_count_30d
        OPTIONAL MATCH (flagged:Account {is_flagged: true})-[:TRANSFERRED_TO]->(recipient)
        RETURN
            recipient.is_flagged        AS is_flagged,
            unique_senders_30d,
            total_received_30d,
            transaction_count_30d,
            count(flagged)              AS flagged_senders_count
        """

        try:
            async with self.driver.session() as session:
                result = await session.run(query, recipient_id=recipient_id)
                record = await result.single()

                if not record:
                    return {
                        "recipient_id"       : recipient_id,
                        "found_in_graph"     : False,
                        "graph_risk"         : 0.0,
                    }

                unique_senders    = record["unique_senders_30d"] or 0
                flagged_senders   = record["flagged_senders_count"] or 0
                is_flagged        = record["is_flagged"] or False
                total_received    = record["total_received_30d"] or 0.0

                # Compute graph risk score
                # High unique senders = money mule (collecting from victims)
                # Flagged senders = connected to known fraud
                graph_risk = 0.0
                if is_flagged:
                    graph_risk += 0.5
                if unique_senders > 10:
                    graph_risk += 0.3
                elif unique_senders > 5:
                    graph_risk += 0.15
                if flagged_senders > 0:
                    graph_risk += min(flagged_senders * 0.1, 0.3)

                graph_risk = min(graph_risk, 1.0)

                return {
                    "recipient_id"          : recipient_id,
                    "found_in_graph"        : True,
                    "is_flagged"            : is_flagged,
                    "unique_senders_30d"    : unique_senders,
                    "flagged_senders_count" : flagged_senders,
                    "total_received_30d"    : float(total_received),
                    "graph_risk"            : round(graph_risk, 3),
                }

        except Exception as e:
            logger.error("Neo4j query failed: {}", str(e))
            return {"error": str(e), "graph_risk": 0.0}

    async def get_sender_network_risk(self, sender_id: str) -> dict:
        """
        Query 2: Is the sender connected to any known fraud cases?

        Checks if this sender has previously sent money to flagged accounts.
        A legitimate user should have 0 flagged connections.
        """
        if not self.driver:
            return {"error": "Neo4j not available", "sender_network_risk": 0.0}

        query = """
        MATCH (sender:Account {account_id: $sender_id})
        OPTIONAL MATCH (sender)-[:TRANSFERRED_TO]->(flagged:Account {is_flagged: true})
        RETURN
            sender.is_flagged               AS sender_is_flagged,
            count(flagged)                  AS flagged_recipients_count
        """

        try:
            async with self.driver.session() as session:
                result = await session.run(query, sender_id=sender_id)
                record = await result.single()

                if not record:
                    return {
                        "sender_id"              : sender_id,
                        "found_in_graph"         : False,
                        "sender_network_risk"    : 0.0,
                    }

                flagged_recipients = record["flagged_recipients_count"] or 0
                sender_flagged     = record["sender_is_flagged"] or False

                network_risk = 0.0
                if sender_flagged:
                    network_risk += 0.6
                if flagged_recipients > 0:
                    network_risk += min(flagged_recipients * 0.15, 0.4)

                return {
                    "sender_id"                 : sender_id,
                    "found_in_graph"            : True,
                    "sender_is_flagged"         : sender_flagged,
                    "flagged_recipients_count"  : flagged_recipients,
                    "sender_network_risk"       : round(min(network_risk, 1.0), 3),
                }

        except Exception as e:
            logger.error("Neo4j sender query failed: {}", str(e))
            return {"error": str(e), "sender_network_risk": 0.0}

    async def get_multi_hop_risk(self, account_id: str) -> dict:
        """
        Query 3: Multi-hop fraud network analysis.

        WHY?

        Current graph analysis only checks direct connections:

            A -> B

        Real fraud networks look like:

            Fraud_A -> Mule_B -> Mule_C -> Mule_D

        This query searches up to 3 hops away and checks whether
        the account is connected to flagged accounts indirectly.

        Returns:
            suspicious_neighbors
            max_depth
            multi_hop_risk
        """

        if not self.driver:
            return {
                "error": "Neo4j not available",
                "multi_hop_risk": 0.0,
            }

        query = """
        MATCH path =
            (account:Account {account_id: $account_id})
            -[:TRANSFERRED_TO*1..3]-
            (neighbor:Account)

        WHERE neighbor.is_flagged = true

        RETURN
            count(DISTINCT neighbor) AS suspicious_neighbors,
            max(length(path))        AS max_depth
        """

        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    account_id=account_id
                )

                record = await result.single()

                if not record:
                    return {
                        "account_id": account_id,
                        "found_in_graph": False,
                        "suspicious_neighbors": 0,
                        "max_depth": 0,
                        "multi_hop_risk": 0.0,
                    }

                suspicious_neighbors = (
                    record["suspicious_neighbors"] or 0
                )

                max_depth = (
                    record["max_depth"] or 0
                )

                # ──────────────────────────────────────
                # Risk scoring
                # ──────────────────────────────────────

                multi_hop_risk = 0.0

                if suspicious_neighbors >= 5:
                    multi_hop_risk += 0.40

                elif suspicious_neighbors >= 2:
                    multi_hop_risk += 0.20

                if max_depth >= 3:
                    multi_hop_risk += 0.10

                multi_hop_risk = round(
                    min(multi_hop_risk, 1.0),
                    3
                )

                return {
                    "account_id": account_id,
                    "found_in_graph": True,
                    "suspicious_neighbors": suspicious_neighbors,
                    "max_depth": max_depth,
                    "multi_hop_risk": multi_hop_risk,
                }

        except Exception as e:
            logger.error(
                "Neo4j multi-hop query failed: {}",
                str(e)
            )

            return {
                "error": str(e),
                "multi_hop_risk": 0.0,
            }



    async def write_transaction_edge(
        self,
        sender_id      : str,
        recipient_id   : str,
        transaction_id : str,
        amount         : float,
        verdict        : str,
        is_fraud       : bool,
        timestamp      : str,
    ) -> bool:
        """
        Write a new transaction edge to the Neo4j graph.

        Every resolved transaction (APPROVE, HOLD, DENY) gets written here.
        This keeps the fraud graph current and up to date.

        WHY write APPROVE transactions too?
        The graph needs legitimate connections to understand normal patterns.
        Without them, every new recipient looks suspicious.
        """
        if not self.driver:
            return False

        query = """
        MERGE (sender:Account {account_id: $sender_id})
        MERGE (recipient:Account {account_id: $recipient_id})
        CREATE (sender)-[:TRANSFERRED_TO {
            transaction_id : $transaction_id,
            amount         : $amount,
            verdict        : $verdict,
            is_fraud       : $is_fraud,
            timestamp      : datetime($timestamp)
        }]->(recipient)
        SET recipient.is_flagged = CASE
            WHEN $is_fraud = true THEN true
            ELSE recipient.is_flagged
        END
        RETURN true AS written
        """

        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    sender_id      = sender_id,
                    recipient_id   = recipient_id,
                    transaction_id = transaction_id,
                    amount         = amount,
                    verdict        = verdict,
                    is_fraud       = is_fraud,
                    timestamp      = timestamp,
                )
                record = await result.single()
                return bool(record and record["written"])
        except Exception as e:
            logger.error("Neo4j write failed: {}", str(e))
            return False


# ── Redis result store ────────────────────────────────────────────────────

class InvestigationStore:
    """
    Stores investigation results in Redis.

    When the worker completes a deep investigation, it saves the report here.
    The frontend dashboard can then fetch it for the analyst to review.

    Key format: investigation:{transaction_id}
    TTL: 7 days (investigations expire after a week)
    """

    def __init__(self, redis_url: str = settings.REDIS_URL):
        self.redis_url = redis_url
        self.client    = None

    async def connect(self) -> None:
        try:
            import redis.asyncio as aioredis
            self.client = aioredis.from_url(self.redis_url, decode_responses=True)
            await self.client.ping()
            logger.info("Connected to Redis at {}", self.redis_url)
        except Exception as e:
            logger.error("Redis connection failed: {} — results won't be stored", str(e))
            self.client = None

    async def save_investigation(
        self,
        transaction_id : str,
        report         : dict,
        ttl_seconds    : int = 604800,  # 7 days
    ) -> None:
        if not self.client:
            logger.warning("Redis not available — investigation report logged only")
            logger.info("Investigation report: {}", json.dumps(report))
            return

        try:
            key = f"investigation:{transaction_id}"
            await self.client.setex(key, ttl_seconds, json.dumps(report))
            logger.info("Investigation saved to Redis | key={}", key)
        except Exception as e:
            logger.error("Redis save failed: {}", str(e))


# ── Main worker loop ──────────────────────────────────────────────────────

async def process_hold_event(
    event_data  : dict,
    investigator: GraphInvestigator,
    store       : InvestigationStore,
) -> None:
    """
    Process a single HOLD event from Kafka.

    This is the core investigation function.
    It runs all graph queries and saves the final report.

    Args:
        event_data  : the HOLD event payload from Kafka
        investigator: Neo4j graph query engine
        store       : Redis result store
    """
    try:
        transaction    = event_data["transaction"]
        inference      = event_data["inference_result"]
        transaction_id = transaction["transaction_id"]
        sender_id      = transaction["account_id"]
        recipient_id   = transaction["recipient_id"]
        amount         = transaction["amount"]

        logger.info(
            "Processing HOLD event | txn={} | sender={} | recipient={} | amount={}",
            transaction_id, sender_id, recipient_id, amount
        )

        # ── Run SHAP in background worker ───────────────────────────
        try:
            import numpy as np
            from app.schemas.transaction import EngineeredFeatures
            from app.inference import registry, _run_shap

            features_obj = EngineeredFeatures(**event_data["features"])
            features_array = np.array(features_obj.to_numpy_array(), dtype=np.float32).reshape(1, -1)

            if not registry.is_loaded:
                registry.load_all()

            shap_features = _run_shap(features_array)
            logger.info("SHAP computation completed in background worker | txn={}", transaction_id)
        except Exception as e:
            logger.warning("SHAP computation failed in background worker: {} | txn={}", str(e), transaction_id)
            shap_features = []

        # ── Run graph investigations in parallel ──────────────────────
        # asyncio.gather runs both queries simultaneously — faster than sequential
        
        recipient_risk, sender_risk, multi_hop_risk = await asyncio.gather(
            investigator.get_recipient_risk(recipient_id),
            investigator.get_sender_network_risk(sender_id),
            investigator.get_multi_hop_risk(recipient_id),
        )

        # ── Compute final investigation score ─────────────────────────
        layer1_score  = inference.get("combined_risk_score", 0.5)
        graph_risk    = recipient_risk.get("graph_risk", 0.0)
        network_risk  = sender_risk.get("sender_network_risk", 0.0)
        multi_hop_score = multi_hop_risk.get("multi_hop_risk", 0.0)

        logger.info(
            "Multi-hop analysis | neighbors={} | depth={} | risk={}",
            multi_hop_risk.get("suspicious_neighbors", 0),
            multi_hop_risk.get("max_depth", 0),
            multi_hop_score,
        )
        # Weighted combination: Layer 1 (50%) + Graph (30%) + Network (20%)
        final_score = (
            0.45 * layer1_score +
            0.25 * graph_risk +
            0.15 * network_risk +
            0.15 * multi_hop_score
        )
        
        final_score = round(min(final_score, 1.0), 4)

        # ── Determine updated verdict ─────────────────────────────────
        if final_score >= 0.75:
            updated_verdict = "DENY"
            action          = "ESCALATE_TO_DENY"
        elif final_score >= 0.50:
            updated_verdict = "HOLD"
            action          = "MAINTAIN_HOLD"
        else:
            updated_verdict = "APPROVE"
            action          = "RELEASE_HOLD"

        # ── Build investigation report ────────────────────────────────
        report = {
            "transaction_id"    : transaction_id,
            "investigated_at"   : datetime.now(timezone.utc).isoformat(),
            "layer1_score"      : layer1_score,
            "graph_risk"        : graph_risk,
            "network_risk"      : network_risk,
            "multi_hop_score": multi_hop_score,
            "multi_hop_analysis": multi_hop_risk,
            "final_score"       : final_score,
            "updated_verdict"   : updated_verdict,
            "action"            : action,
            "recipient_analysis": recipient_risk,
            "sender_analysis"   : sender_risk,
            "shap_features"     : shap_features,
            "recommendation"    : (
                f"Final risk score: {final_score:.3f}. "
                f"Action: {action}. "
                f"Recipient graph risk: {graph_risk:.3f}. "
                f"Sender network risk: {network_risk:.3f}."
            ),
        }

        logger.info(
            "Investigation complete | txn={} | final_score={} | action={}",
            transaction_id, final_score, action
        )

        # ── Save report to Redis ──────────────────────────────────────
        await store.save_investigation(transaction_id, report)

        # ── Broadcast INVESTIGATION_COMPLETE to dashboard via Redis pubsub ──
        if store.client:
            try:
                inv_payload = json.dumps({
                    "type": "INVESTIGATION_COMPLETE",
                    "transaction_id": transaction_id,
                    "forensic_report": report.get("recommendation", "Investigation complete."),
                    "final_confidence": "HIGH" if final_score >= 0.75 else ("MEDIUM" if final_score >= 0.50 else "LOW"),
                    "graph_risk": "CRITICAL" if graph_risk >= 0.5 else ("HIGH" if graph_risk >= 0.3 else "LOW"),
                    "device_risk": "UNKNOWN",
                    "ip_vpn": False,
                    "investigation_duration_ms": 0.0,
                    "shap_features": shap_features,
                })
                await store.client.publish("dashboard_alerts", inv_payload)
                logger.info("INVESTIGATION_COMPLETE published to dashboard | txn={}", transaction_id)
            except Exception as pub_e:
                logger.warning("Failed to publish investigation event: {}", str(pub_e))

        # ── Write transaction to Neo4j graph ─────────────────────────
        is_fraud = updated_verdict in ("DENY", "HOLD")
        await investigator.write_transaction_edge(
            sender_id      = sender_id,
            recipient_id   = recipient_id,
            transaction_id = transaction_id,
            amount         = float(amount),
            verdict        = updated_verdict,
            is_fraud       = is_fraud,
            timestamp      = transaction.get("timestamp",
                             datetime.now(timezone.utc).isoformat()),
        )

    except Exception as e:
        logger.error("Failed to process HOLD event: {}", str(e))
        import traceback
        logger.error(traceback.format_exc())


async def run_worker() -> None:
    """
    Main worker loop — connects to Kafka and processes HOLD events.

    Runs forever until stopped (Ctrl+C).
    Automatically reconnects if Kafka goes down.
    """
    # ── Connect to Neo4j and Redis ────────────────────────────────────
    investigator = GraphInvestigator(
        uri = settings.NEO4J_URI,
        user = settings.NEO4J_USER,
        password = settings.NEO4J_PASSWORD
    )
    store = InvestigationStore(redis_url=settings.REDIS_URL)

    await investigator.connect()
    await store.connect()

    # ── Connect to Kafka ──────────────────────────────────────────────
    logger.info("Starting Kafka consumer — listening on 'transactions.hold'...")

    try:
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            "transactions.hold",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,   # external port from docker-compose
            group_id           = "detection_workers",
            auto_offset_reset  = "earliest",          # process from beginning if new consumer
            enable_auto_commit = False,               # manual commit — ensures no lost events
            value_deserializer = lambda m: json.loads(m.decode("utf-8")),
        )

        await consumer.start()
        logger.info("Kafka consumer started — waiting for HOLD events...")

        try:
            async for message in consumer:
                logger.info(
                    "HOLD event received | partition={} | offset={}",
                    message.partition,
                    message.offset,
                )

                await process_hold_event(
                    # pyrefly: ignore [bad-argument-type]
                    message.value,
                    investigator,
                    store,
                )

                # Commit offset AFTER successful processing
                # If processing fails, the event will be retried
                await consumer.commit()

        finally:
            await consumer.stop()

    except ImportError:
        logger.error("aiokafka not installed. Run: pip install aiokafka")
    except Exception as e:
        logger.error("Kafka consumer error: {}", str(e))
    finally:
        await investigator.close()


if __name__ == "__main__":
    logger.info("Fin-Guardian AI Detection Worker starting...")
    asyncio.run(run_worker())
