"""
app/agents/tools/graph_query.py
────────────────────────────────
Neo4j graph query tool for the Fraud Detective agent.
Performs multi-hop account relationship analysis to detect
money mule chains, fraud rings, and suspicious centrality.

Falls back gracefully if Neo4j is offline.
"""

from __future__ import annotations

from loguru import logger


def query_recipient_network(recipient_id: str) -> dict:
    """
    Analyse the recipient account's position in the financial network.

    Runs multi-hop Cypher queries (1..4 hops) to detect:
    - Direct connections to known fraud accounts
    - Money mule chains
    - High centrality (collector point for many victims)
    - Circular transfer patterns (money laundering)

    Returns a dict with keys:
        recipient_id, direct_fraud_connections, two_hop_suspicious_count,
        fraud_cluster_size, circular_transfers_found, risk_level, summary
    """
    try:
        from neo4j import GraphDatabase  # type: ignore[import]
        from app.core.settings import settings

        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )

        with driver.session() as session:
            results = _run_queries(session, recipient_id)

        driver.close()
        return results

    except Exception as e:
        logger.warning("Neo4j graph query failed for {}: {}", recipient_id, str(e))
        return _fallback_result(recipient_id, str(e))


def _run_queries(session: object, recipient_id: str) -> dict:  # type: ignore[type-arg]
    """Execute multi-hop Cypher queries against Neo4j."""

    # 1. Direct fraud connections (1-hop)
    direct_query = """
    MATCH (victim)-[:TRANSFERRED_TO]->(recipient {account_id: $rid})
    WHERE victim.is_fraud = true OR recipient.is_fraud = true
    RETURN count(*) AS count
    """

    # 2. Two-hop suspicious network
    two_hop_query = """
    MATCH path=(a)-[:TRANSFERRED_TO*1..2]->(b {account_id: $rid})
    WHERE any(n IN nodes(path) WHERE n.is_fraud = true)
    RETURN count(path) AS count
    """

    # 3. Fraud cluster size (how many fraud nodes within 4 hops)
    cluster_query = """
    MATCH path=(a)-[:TRANSFERRED_TO*1..4]->(b {account_id: $rid})
    WITH nodes(path) AS path_nodes
    RETURN sum(CASE WHEN any(n IN path_nodes WHERE n.is_fraud = true) THEN 1 ELSE 0 END) AS fraud_count
    """

    # 4. Circular transfers (money laundering pattern)
    circular_query = """
    MATCH path=(a {account_id: $rid})-[:TRANSFERRED_TO*2..4]->(a)
    RETURN count(path) AS count
    """

    try:
        direct_count = session.run(direct_query, rid=recipient_id).single()["count"]  # type: ignore[union-attr]
    except Exception:
        direct_count = 0

    try:
        two_hop_count = session.run(two_hop_query, rid=recipient_id).single()["count"]  # type: ignore[union-attr]
    except Exception:
        two_hop_count = 0

    try:
        cluster_size = session.run(cluster_query, rid=recipient_id).single()["fraud_count"]  # type: ignore[union-attr]
    except Exception:
        cluster_size = 0

    try:
        circular_count = session.run(circular_query, rid=recipient_id).single()["count"]  # type: ignore[union-attr]
    except Exception:
        circular_count = 0

    # Risk classification
    if direct_count >= 5 or cluster_size >= 10 or circular_count > 0:
        risk_level = "CRITICAL"
    elif direct_count >= 2 or two_hop_count >= 5 or cluster_size >= 3:
        risk_level = "HIGH"
    elif direct_count >= 1 or two_hop_count >= 2:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "recipient_id": recipient_id,
        "direct_fraud_connections": int(direct_count),
        "two_hop_suspicious_count": int(two_hop_count),
        "fraud_cluster_size": int(cluster_size),
        "circular_transfers_found": int(circular_count),
        "risk_level": risk_level,
        "summary": _build_summary(
            recipient_id, int(direct_count), int(two_hop_count),
            int(cluster_size), int(circular_count), risk_level,
        ),
    }


def _build_summary(
    recipient_id: str,
    direct: int,
    two_hop: int,
    cluster: int,
    circular: int,
    risk_level: str,
) -> str:
    parts = [f"Recipient '{recipient_id}':"]
    if direct > 0:
        parts.append(f"{direct} direct connections to known fraud accounts.")
    if two_hop > 0:
        parts.append(f"{two_hop} suspicious accounts within 2 hops.")
    if cluster > 0:
        parts.append(f"Part of a fraud cluster of {cluster} accounts.")
    if circular > 0:
        parts.append(f"WARNING: {circular} circular transfer pattern(s) detected — money laundering signature.")
    if not any([direct, two_hop, cluster, circular]):
        parts.append("No fraud connections found in 4-hop network.")
    parts.append(f"Overall graph risk: {risk_level}.")
    return " ".join(parts)


def _fallback_result(recipient_id: str, error: str) -> dict:
    return {
        "recipient_id": recipient_id,
        "direct_fraud_connections": 0,
        "two_hop_suspicious_count": 0,
        "fraud_cluster_size": 0,
        "circular_transfers_found": 0,
        "risk_level": "UNKNOWN",
        "summary": f"Graph analysis unavailable (Neo4j offline: {error}). Falling back to ML signals only.",
    }
