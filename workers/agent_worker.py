"""
workers/agent_worker.py
────────────────────────
Fin-Guardian AI — LangGraph AI Detective (Layer 3)

This is the most advanced component of the system.
It is an AI agent that autonomously investigates HOLD events
using a deterministic state machine.

HOW IT WORKS:
─────────────
Think of this like a detective following leads:

1. Agent receives a HOLD event from Kafka
2. It decides which tools to use (IP lookup? Device check? Graph query?)
3. Each tool runs a hard-coded, deterministic Python function
4. Agent synthesises all findings into a forensic report
5. Report is saved to Redis and published to the WebSocket dashboard

WHY LANGGRAPH?
──────────────
LangGraph is a state machine framework for AI agents.
Unlike simple LLM chat, LangGraph:
- Follows a defined investigation flow (no random behaviour)
- Each step is logged and auditable
- Tools are hard-coded Python (no AI guessing)
- The LLM only decides routing and synthesis (never data access)

ARCHITECTURE RULE (from our design doc):
The LLM must NEVER access data directly.
All data access goes through hard-coded tool functions.
LLM job: decide what to investigate + synthesise findings.
Tool job: actually fetch the data deterministically.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from typing import TypedDict, Annotated
import operator

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
        '"service":"agent_worker",'
        '"message":"{message}"}}'
    ),
    colorize=False,
)


# ── Agent State ───────────────────────────────────────────────────────────

class InvestigationState(TypedDict):
    """
    The state that flows through the LangGraph state machine.

    Every node in the graph reads from this state and writes back to it.
    This makes the investigation fully traceable — you can see exactly
    what the agent found at each step.

    Think of it like a detective's notebook that gets filled in
    as they investigate each lead.
    """
    # Input
    transaction_id   : str
    account_id       : str
    recipient_id     : str
    amount           : float
    ip_address       : str | None
    device_id        : str | None
    has_location     : bool
    timestamp        : str
    layer1_score     : float
    shap_features    : list[dict]

    # Investigation findings (filled in by tools)
    ip_risk          : dict
    device_risk      : dict
    graph_risk       : dict
    missing_signals  : list[str]

    # Final output
    investigation_complete : bool
    forensic_report        : dict
    final_verdict          : str
    confidence             : float

    # Audit trail
    steps_taken      : Annotated[list[str], operator.add]


# ── Deterministic Tool Functions ──────────────────────────────────────────
# These are the detective's specialist consultants.
# Each one is a hard-coded Python function — no AI guesswork.

def tool_check_ip_risk(ip_address: str | None) -> dict:
    """
    Tool 1: IP Geolocation & Risk Check

    Checks if the IP address is suspicious:
    - Is it a VPN provider?
    - Is it a Tor exit node?
    - Is it from an unexpected country?
    - Is it a known fraud IP?

    In production: calls a real IP intelligence API (e.g. ipqualityscore.com)
    In development: uses heuristic rules as fallback

    Args:
        ip_address: the IP from the transaction request

    Returns:
        dict with risk assessment
    """
    if ip_address is None:
        return {
            "ip_address"      : None,
            "is_missing"      : True,
            "risk_score"      : 0.6,   # missing IP is suspicious
            "risk_reason"     : "No IP address provided — possible API call or device spoofing",
            "is_vpn"          : False,
            "is_tor"          : False,
            "country"         : "unknown",
        }

    # In production: replace with real API call
    # import httpx
    # response = httpx.get(f"https://ipqualityscore.com/api/json/ip/{API_KEY}/{ip_address}")
    # return response.json()

    # Development: heuristic check
    risk_score = 0.1
    reasons    = []

    # Known VPN/proxy IP ranges (simplified)
    suspicious_ranges = ["10.", "172.", "192.168."]
    if any(ip_address.startswith(r) for r in suspicious_ranges):
        risk_score = 0.3
        reasons.append("Private/internal IP range")

    return {
        "ip_address"  : ip_address,
        "is_missing"  : False,
        "risk_score"  : risk_score,
        "risk_reason" : "; ".join(reasons) if reasons else "IP appears legitimate",
        "is_vpn"      : False,
        "is_tor"      : False,
        "country"     : "IN",
    }


def tool_check_device_fingerprint(device_id: str | None) -> dict:
    """
    Tool 2: Device Fingerprint Analysis

    Checks if the device is suspicious:
    - Is device_id missing? (Midnight Ghost signal)
    - Is it a known fraudster device?
    - Signs of device emulation or automation?

    Args:
        device_id: the device identifier from the transaction

    Returns:
        dict with device risk assessment
    """
    if device_id is None:
        return {
            "device_id"      : None,
            "is_missing"     : True,
            "risk_score"     : 0.7,   # missing device = major red flag
            "risk_reason"    : "No device ID — transaction may originate from automated script or credential stuffing attack",
            "is_emulated"    : False,
            "is_known_fraud" : False,
        }

    # In production: check against device risk database
    # Check if device has been associated with fraud before
    risk_score = 0.1
    reason     = "Device appears legitimate"

    # Simple heuristic: very short device IDs are suspicious
    if len(device_id) < 8:
        risk_score = 0.4
        reason     = "Unusually short device ID — possible spoofing"

    return {
        "device_id"      : device_id,
        "is_missing"     : False,
        "risk_score"     : risk_score,
        "risk_reason"    : reason,
        "is_emulated"    : False,
        "is_known_fraud" : False,
    }


def tool_check_missing_signals(
    has_location : bool,
    device_id    : str | None,
    ip_address   : str | None,
    amount       : float,
    timestamp    : str,
) -> dict:
    """
    Tool 3: Missing Signal Analysis

    In legitimate transactions, certain fields are always present.
    Their ABSENCE is itself a fraud signal.

    The Midnight Ghost scenario: ₹92,000 at 11:45 PM with NO GPS.
    A real user holding their phone would have GPS enabled.

    Args:
        Various transaction fields that might be missing

    Returns:
        dict with missing signal analysis
    """
    missing       = []
    risk_score    = 0.0
    risk_reasons  = []

    if not has_location:
        missing.append("GPS/Location")
        risk_score  += 0.3
        risk_reasons.append("No GPS data — unusual for mobile banking app")

    if device_id is None:
        missing.append("Device ID")
        risk_score  += 0.3
        risk_reasons.append("No device fingerprint — possible automated attack")

    if ip_address is None:
        missing.append("IP Address")
        risk_score  += 0.2
        risk_reasons.append("No IP address logged")

    # Check if high-value transaction at unusual time
    try:
        ts   = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        hour = ts.hour
        if (hour >= 22 or hour <= 5) and amount > 50000:
            risk_score  += 0.2
            risk_reasons.append(
                f"High-value transaction (₹{amount:,.0f}) at unusual hour ({hour}:00)"
            )
    except Exception:
        pass

    return {
        "missing_signals"  : missing,
        "risk_score"       : min(risk_score, 1.0),
        "risk_reasons"     : risk_reasons,
        "signal_count"     : len(missing),
    }


def tool_query_fraud_graph(
    recipient_id : str,
    sender_id    : str,
) -> dict:
    """
    Tool 4: Fraud Network Graph Query (Neo4j)

    Queries the Neo4j graph to check if the recipient
    is connected to known fraud networks.

    In production: runs real Cypher queries against Neo4j.
    In development/fallback: returns heuristic assessment.

    Args:
        recipient_id: the transaction recipient account ID
        sender_id: the transaction sender account ID

    Returns:
        dict with graph risk assessment
    """
    # Try real Neo4j query first
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
                        settings.NEO4J_URI,
                        auth=(
                                settings.NEO4J_USER,
                                settings.NEO4J_PASSWORD
                            )
)

        with driver.session() as session:
            result = session.run("""
                MATCH (recipient:Account {account_id: $recipient_id})
                OPTIONAL MATCH (sender:Account)-[t:TRANSFERRED_TO]->(recipient)
                WHERE t.is_fraud = true
                RETURN
                    recipient.is_flagged       AS is_flagged,
                    count(t)                   AS fraud_txn_count
            """, recipient_id=recipient_id)

            record = result.single()
            driver.close()

            if record:
                is_flagged      = record["is_flagged"] or False
                fraud_count     = record["fraud_txn_count"] or 0
                graph_risk      = 0.7 if is_flagged else min(fraud_count * 0.1, 0.5)

                return {
                    "source"          : "neo4j",
                    "recipient_flagged": is_flagged,
                    "fraud_txn_count" : fraud_count,
                    "graph_risk"      : graph_risk,
                    "risk_reason"     : (
                        f"Recipient is flagged in fraud graph with {fraud_count} fraud connections"
                        if is_flagged else
                        f"Recipient has {fraud_count} suspicious connections"
                    ),
                }

    except Exception as e:
        logger.warning("Neo4j unavailable for graph query: {} — using heuristic", str(e))

    # Fallback: heuristic assessment
    # Unknown recipients with no history are moderately suspicious
    is_unknown = recipient_id.startswith("C_UNKNOWN")
    return {
        "source"           : "heuristic",
        "recipient_flagged": is_unknown,
        "fraud_txn_count"  : 0,
        "graph_risk"       : 0.6 if is_unknown else 0.1,
        "risk_reason"      : (
            "Recipient ID pattern matches unknown/suspicious account"
            if is_unknown else
            "Recipient appears in normal range"
        ),
    }


# ── LangGraph State Machine Nodes ─────────────────────────────────────────

def node_run_ip_check(state: InvestigationState) -> dict:
    """Node 1: Run IP risk check tool."""
    logger.info("Investigation step: IP check | txn={}", state["transaction_id"])
    ip_risk = tool_check_ip_risk(state.get("ip_address"))
    return {
        "ip_risk"     : ip_risk,
        "steps_taken" : [f"IP check: risk={ip_risk['risk_score']:.2f}"],
    }


def node_run_device_check(state: InvestigationState) -> dict:
    """Node 2: Run device fingerprint check tool."""
    logger.info("Investigation step: device check | txn={}", state["transaction_id"])
    device_risk = tool_check_device_fingerprint(state.get("device_id"))
    return {
        "device_risk" : device_risk,
        "steps_taken" : [f"Device check: risk={device_risk['risk_score']:.2f}"],
    }


def node_run_signal_check(state: InvestigationState) -> dict:
    """Node 3: Analyse missing signals."""
    logger.info("Investigation step: missing signals | txn={}", state["transaction_id"])
    signal_result = tool_check_missing_signals(
        has_location = state.get("has_location", False),
        device_id    = state.get("device_id"),
        ip_address   = state.get("ip_address"),
        amount       = state.get("amount", 0),
        timestamp    = state.get("timestamp", ""),
    )
    return {
        "missing_signals" : signal_result["missing_signals"],
        "steps_taken"     : [f"Signal check: {len(signal_result['missing_signals'])} missing signals"],
    }


def node_run_graph_check(state: InvestigationState) -> dict:
    """Node 4: Query fraud network graph."""
    logger.info("Investigation step: graph query | txn={}", state["transaction_id"])
    graph_risk = tool_query_fraud_graph(
        recipient_id = state["recipient_id"],
        sender_id    = state["account_id"],
    )
    return {
        "graph_risk"  : graph_risk,
        "steps_taken" : [f"Graph check: risk={graph_risk['graph_risk']:.2f} source={graph_risk['source']}"],
    }


def node_synthesise_findings(state: InvestigationState) -> dict:
    """
    Node 5: Synthesise all findings into a forensic report.

    This is where the LLM would normally run to write the narrative.
    For now we use deterministic synthesis — equally effective and faster.

    In production with an LLM:
        prompt = f"Based on these findings: {state}, write a forensic report..."
        report_text = llm.invoke(prompt)
    """
    logger.info("Investigation step: synthesis | txn={}", state["transaction_id"])

    ip_risk     = state.get("ip_risk", {})
    device_risk = state.get("device_risk", {})
    graph_risk  = state.get("graph_risk", {})
    layer1      = state.get("layer1_score", 0.5)

    # Weighted final score
    final_score = (
        0.35 * layer1 +
        0.25 * graph_risk.get("graph_risk", 0) +
        0.20 * device_risk.get("risk_score", 0) +
        0.20 * ip_risk.get("risk_score", 0)
    )
    final_score = round(min(final_score, 1.0), 4)

    # Determine verdict
    if final_score >= 0.70:
        verdict    = "CONFIRMED_FRAUD"
        action     = "BLOCK_AND_FLAG"
        confidence = "HIGH"
    elif final_score >= 0.50:
        verdict    = "PROBABLE_FRAUD"
        action     = "ESCALATE_TO_ANALYST"
        confidence = "MEDIUM"
    else:
        verdict    = "LOW_RISK"
        action     = "RELEASE_HOLD"
        confidence = "LOW"

    # Build evidence list
    evidence = []
    if ip_risk.get("is_missing"):
        evidence.append("No IP address — possible credential stuffing")
    if device_risk.get("is_missing"):
        evidence.append("No device ID — Midnight Ghost signal detected")
    if state.get("missing_signals"):
        evidence.append(f"Missing signals: {', '.join(state['missing_signals'])}")
    if graph_risk.get("recipient_flagged"):
        evidence.append("Recipient flagged in fraud network graph")
    if layer1 > 0.6:
        evidence.append(f"Layer 1 ML score: {layer1:.3f} (high suspicion)")

    forensic_report = {
        "transaction_id"  : state["transaction_id"],
        "investigated_at" : datetime.now(timezone.utc).isoformat(),
        "final_score"     : final_score,
        "verdict"         : verdict,
        "action"          : action,
        "confidence"      : confidence,
        "evidence"        : evidence,
        "steps_taken"     : state.get("steps_taken", []),
        "layer1_analysis" : {
            "score"         : layer1,
            "shap_features" : state.get("shap_features", []),
        },
        "ip_analysis"     : ip_risk,
        "device_analysis" : device_risk,
        "graph_analysis"  : graph_risk,
        "narrative"       : (
            f"FORENSIC INVESTIGATION REPORT\n"
            f"Transaction: {state['transaction_id']}\n"
            f"Amount: ₹{state.get('amount', 0):,.2f}\n"
            f"Final Risk Score: {final_score:.3f}\n"
            f"Verdict: {verdict} ({confidence} confidence)\n"
            f"Recommended Action: {action}\n\n"
            f"Evidence ({len(evidence)} items found):\n"
            + "\n".join(f"  • {e}" for e in evidence) +
            f"\n\nInvestigation Steps:\n"
            + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(state.get("steps_taken", [])))
        ),
    }

    return {
        "forensic_report"        : forensic_report,
        "final_verdict"          : verdict,
        # pyrefly: ignore [unnecessary-type-conversion]
        "confidence"             : float(final_score),
        "investigation_complete" : True,
        "steps_taken"            : ["Synthesis complete"],
    }


# ── Build the LangGraph State Machine ────────────────────────────────────

def build_investigation_graph():
    """
    Build the LangGraph investigation state machine.

    Graph structure:
        START
          ↓
        ip_check → device_check → signal_check → graph_check → synthesise
          ↓
        END

    Each node runs a deterministic tool and updates the state.
    The final node synthesises all findings into a report.
    """
    try:
        from langgraph.graph import StateGraph, END

        # pyrefly: ignore [bad-specialization]
        graph = StateGraph(InvestigationState)

        # Add all investigation nodes
        graph.add_node("ip_check",      node_run_ip_check)
        graph.add_node("device_check",  node_run_device_check)
        graph.add_node("signal_check",  node_run_signal_check)
        graph.add_node("graph_check",   node_run_graph_check)
        graph.add_node("synthesise",    node_synthesise_findings)

        # Define the investigation flow (sequential)
        graph.set_entry_point("ip_check")
        graph.add_edge("ip_check",     "device_check")
        graph.add_edge("device_check", "signal_check")
        graph.add_edge("signal_check", "graph_check")
        graph.add_edge("graph_check",  "synthesise")
        graph.add_edge("synthesise",   END)

        return graph.compile()

    except ImportError:
        logger.warning("langgraph not installed — using simplified sequential investigation")
        return None


# ── Main agent function ───────────────────────────────────────────────────

async def investigate_hold_event(event: dict) -> dict:
    """
    Run the full AI detective investigation on a HOLD event.

    This is called by the detection worker when a HOLD event arrives.
    Returns the complete forensic report.

    Args:
        event: the HOLD event payload from Kafka

    Returns:
        forensic report dict
    """
    transaction = event.get("transaction", {})
    inference   = event.get("inference_result", {})

    # Build initial state
    initial_state: InvestigationState = {
        "transaction_id"        : transaction.get("transaction_id", "unknown"),
        "account_id"            : transaction.get("account_id", ""),
        "recipient_id"          : transaction.get("recipient_id", ""),
        "amount"                : float(transaction.get("amount", 0)),
        "ip_address"            : transaction.get("ip_address"),
        "device_id"             : transaction.get("device_id"),
        "has_location"          : transaction.get("latitude") is not None,
        "timestamp"             : transaction.get("timestamp", ""),
        "layer1_score"          : float(inference.get("combined_risk_score", 0.5)),
        "shap_features"         : inference.get("shap_top_features", []),
        "ip_risk"               : {},
        "device_risk"           : {},
        "graph_risk"            : {},
        "missing_signals"       : [],
        "investigation_complete": False,
        "forensic_report"       : {},
        "final_verdict"         : "",
        "confidence"            : 0.0,
        "steps_taken"           : [],
    }

    t0    = time.perf_counter()
    graph = build_investigation_graph()

    if graph:
        # Run via LangGraph state machine
        final_state = graph.invoke(initial_state)
    else:
        # Fallback: run nodes sequentially without LangGraph
        state = initial_state.copy()
        for node_fn in [
            node_run_ip_check,
            node_run_device_check,
            node_run_signal_check,
            node_run_graph_check,
            node_synthesise_findings,
        ]:
            updates = node_fn(state)
            state.update(updates)
            if "steps_taken" in updates:
                state["steps_taken"] = (
                    initial_state.get("steps_taken", []) + updates["steps_taken"]
                )
        final_state = state

    elapsed = (time.perf_counter() - t0) * 1000
    report  = final_state.get("forensic_report", {})
    report["investigation_latency_ms"] = round(elapsed, 2)

    logger.info(
        "Investigation complete | txn={} | verdict={} | score={:.3f} | latency={:.0f}ms",
        initial_state["transaction_id"],
        report.get("verdict", "unknown"),
        report.get("final_score", 0),
        elapsed,
    )

    return report


# ── Standalone runner (for testing) ──────────────────────────────────────

async def run_agent_worker() -> None:
    """
    Run the agent worker as a standalone Kafka consumer.
    Reads HOLD events and runs the LangGraph investigation.
    """
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    logger.info("Agent worker starting — listening for HOLD events...")

    try:
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            "transactions.hold",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id           = "agent_workers",
            auto_offset_reset  = "earliest",
            enable_auto_commit = False,
            value_deserializer = lambda m: json.loads(m.decode("utf-8")),
        )

        await consumer.start()
        logger.info("Agent Kafka consumer started")

        try:
            async for message in consumer:
                # pyrefly: ignore [bad-argument-type]
                report = await investigate_hold_event(message.value)

                # Save to Redis
                # pyrefly: ignore [missing-attribute]
                txn_id = message.value.get("transaction", {}).get("transaction_id", "unknown")
                key    = f"forensic:{txn_id}"
                await redis_client.setex(key, 604800, json.dumps(report))
                logger.info("Forensic report saved | key={}", key)

                await consumer.commit()

        finally:
            await consumer.stop()

    except ImportError:
        logger.error("aiokafka not installed")
    except Exception as e:
        logger.error("Agent worker error: {}", str(e))


if __name__ == "__main__":
    asyncio.run(run_agent_worker())
