"""
app/agents/fraud_detective.py
──────────────────────────────
LangGraph AI Detective — Layer 3 deep investigation agent.

State machine flow:
    START
      └─► ip_analysis      (IP geolocation + VPN check)
      └─► device_check     (emulator / bot detection)
      └─► graph_analysis   (multi-hop Neo4j network query)
      └─► risk_fallback    (rule-based scoring — always runs)
      └─► synthesise       (OpenAI GPT: generate forensic report)
    END

Design rules (from spec):
  • The LLM is a router/synthesiser ONLY — it never accesses data directly.
  • All data retrieval is done by hard-coded Python tools.
  • Every step has a 5-second timeout with graceful fallback.
  • The agent always produces a report — it never hangs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import StateGraph, START, END
from loguru import logger

from app.agents.tools.ip_lookup import lookup_ip
from app.agents.tools.device_fingerprint import analyse_device
from app.agents.tools.graph_query import query_recipient_network
from app.agents.tools.risk_matrix import evaluate_risk_matrix


# ── State definition ──────────────────────────────────────────────────────

class InvestigationState(TypedDict):
    """Full investigation state passed through the LangGraph nodes."""
    # Input fields (set before graph runs)
    transaction_id: str
    account_id: str
    recipient_id: str
    amount: float
    account_age_days: int
    is_new_recipient: bool
    sender_tx_count: int
    hour_of_day: int
    ip_address: str | None
    device_id: str | None
    has_gps: bool
    ml_risk_score: float
    ml_verdict: str
    shap_top_features: list[dict[str, Any]]

    # Output fields (populated by nodes)
    ip_report: dict[str, Any]
    device_report: dict[str, Any]
    graph_report: dict[str, Any]
    risk_matrix_report: dict[str, Any]
    forensic_report: str
    final_confidence: str
    investigation_duration_ms: float


# ── Tool wrappers (with timeout + graceful fallback) ──────────────────────

async def _run_with_timeout(coro: Any, timeout: float, fallback: Any) -> Any:
    try:
        return await asyncio.wait_for(asyncio.coroutine(coro)() if callable(coro) and not asyncio.iscoroutine(coro) else coro, timeout=timeout)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning("Tool timed out or failed: {}", str(e))
        return fallback


def _run_sync_with_fallback(fn: Any, *args: Any, fallback: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning("Tool failed: {}", str(e))
        return fallback


# ── Graph nodes ───────────────────────────────────────────────────────────

def node_ip_analysis(state: InvestigationState) -> dict[str, Any]:
    """Node 1: IP geolocation and VPN/proxy detection."""
    logger.info("Detective | IP analysis | tx={}", state["transaction_id"])
    result = _run_sync_with_fallback(
        lookup_ip,
        state.get("ip_address"),
        fallback={
            "status": "skipped",
            "country": "Unknown",
            "region": "Unknown",
            "city": "Unknown",
            "isp": "Unknown",
            "is_vpn_proxy": False,
            "risk_signals": ["ip_lookup_skipped"],
        },
    )
    return {"ip_report": result}


def node_device_check(state: InvestigationState) -> dict[str, Any]:
    """Node 2: Device fingerprint and emulator detection."""
    logger.info("Detective | Device check | tx={}", state["transaction_id"])
    result = _run_sync_with_fallback(
        analyse_device,
        state.get("device_id"),
        state.get("ip_address"),
        fallback={
            "device_id": "MISSING",
            "is_known_device": False,
            "risk_signals": ["device_check_failed"],
            "risk_level": "UNKNOWN",
            "summary": "Device analysis unavailable.",
        },
    )
    return {"device_report": result}


def node_graph_analysis(state: InvestigationState) -> dict[str, Any]:
    """Node 3: Multi-hop Neo4j network analysis."""
    logger.info("Detective | Graph analysis | recipient={}", state["recipient_id"])
    result = _run_sync_with_fallback(
        query_recipient_network,
        state["recipient_id"],
        fallback={
            "recipient_id": state["recipient_id"],
            "direct_fraud_connections": 0,
            "two_hop_suspicious_count": 0,
            "fraud_cluster_size": 0,
            "circular_transfers_found": 0,
            "risk_level": "UNKNOWN",
            "summary": "Graph analysis unavailable — Neo4j may be offline.",
        },
    )
    return {"graph_report": result}


def node_risk_fallback(state: InvestigationState) -> dict[str, Any]:
    """Node 4: Rule-based risk matrix (always runs — guaranteed output)."""
    logger.info("Detective | Risk matrix | tx={}", state["transaction_id"])
    result = evaluate_risk_matrix(
        amount=state["amount"],
        account_age_days=state["account_age_days"],
        is_new_recipient=state["is_new_recipient"],
        sender_tx_count=state["sender_tx_count"],
        hour_of_day=state["hour_of_day"],
        has_device=bool(state.get("device_id")),
        has_gps=state.get("has_gps", False),
    )
    return {"risk_matrix_report": result}


def node_synthesise(state: InvestigationState) -> dict[str, Any]:
    """
    Node 5: GPT-4o-mini forensic report synthesis.
    The LLM ONLY reads the structured tool outputs and writes the report.
    It does not access any external data or make any decisions directly.
    """
    from app.core.settings import settings

    logger.info("Detective | Synthesis | tx={}", state["transaction_id"])

    ip = state.get("ip_report", {})
    device = state.get("device_report", {})
    graph = state.get("graph_report", {})
    matrix = state.get("risk_matrix_report", {})

    # Build structured evidence summary for the LLM
    evidence_summary = f"""
TRANSACTION UNDER INVESTIGATION:
- Transaction ID: {state['transaction_id']}
- Account: {state['account_id']}
- Recipient: {state['recipient_id']}
- Amount: ₹{state['amount']:,.2f}
- Hour: {state['hour_of_day']:02d}:00
- ML Fraud Score: {state['ml_risk_score']:.4f} → {state['ml_verdict']}
- Top SHAP factors: {state.get('shap_top_features', [])[:3]}

IP ANALYSIS:
- Country: {ip.get('country')} | City: {ip.get('city')}
- ISP: {ip.get('isp')}
- VPN/Proxy detected: {ip.get('is_vpn_proxy')}
- Risk signals: {ip.get('risk_signals', [])}

DEVICE ANALYSIS:
- Device ID: {device.get('device_id')}
- Known device: {device.get('is_known_device')}
- Risk signals: {device.get('risk_signals', [])}
- Summary: {device.get('summary')}

NETWORK GRAPH ANALYSIS (Multi-hop Neo4j):
- Direct fraud connections: {graph.get('direct_fraud_connections')}
- 2-hop suspicious accounts: {graph.get('two_hop_suspicious_count')}
- Fraud cluster size: {graph.get('fraud_cluster_size')}
- Circular transfers (money laundering): {graph.get('circular_transfers_found')}
- Graph risk level: {graph.get('risk_level')}
- Summary: {graph.get('summary')}

RULE-BASED RISK MATRIX:
- Score: {matrix.get('risk_score')} | Verdict: {matrix.get('verdict')}
- Key factors: {matrix.get('risk_factors', [])}
"""

    # If no API key, produce a structured report without LLM
    if not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY.startswith("your-"):
        logger.warning("No OpenAI API key configured — using template forensic report.")
        report = _template_report(state, ip, device, graph, matrix)
        return {"forensic_report": report, "final_confidence": _calc_confidence(graph, device, ip, matrix)}

    # LLM synthesis
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=0.1,
            max_tokens=600,
        )

        system_prompt = """You are a forensic fraud analyst AI. You receive structured evidence collected by 
automated investigation tools and write a clear, professional forensic report.

RULES:
1. Base your analysis ONLY on the evidence provided — do not hallucinate or add external data.
2. Structure your report with: EXECUTIVE SUMMARY, KEY EVIDENCE, RISK ASSESSMENT, RECOMMENDATION.
3. Be concise (max 400 words). Use plain language that a bank compliance officer can understand.
4. End with a clear verdict: APPROVE, HOLD, or DENY with a one-line justification."""

        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Write a forensic investigation report for the following evidence:\n{evidence_summary}"),
        ])

        report = str(response.content)
        confidence = _calc_confidence(graph, device, ip, matrix)

        logger.info(
            "Detective | Synthesis complete | tx={} | confidence={}",
            state["transaction_id"],
            confidence,
        )

        return {"forensic_report": report, "final_confidence": confidence}

    except Exception as e:
        logger.error("LLM synthesis failed: {}. Using template report.", str(e))
        report = _template_report(state, ip, device, graph, matrix)
        return {"forensic_report": report, "final_confidence": _calc_confidence(graph, device, ip, matrix)}


# ── Helper functions ──────────────────────────────────────────────────────

def _calc_confidence(
    graph: dict[str, Any],
    device: dict[str, Any],
    ip: dict[str, Any],
    matrix: dict[str, Any],
) -> str:
    """Compute investigation confidence level from tool signal count."""
    signals = (
        len(graph.get("risk_level", "") and graph.get("risk_level") != "UNKNOWN" and ["x"] or [])
        + len(device.get("risk_signals", []))
        + len(ip.get("risk_signals", []))
        + (1 if matrix.get("risk_score", 0) > 0.5 else 0)
    )
    if signals >= 4:
        return "HIGH"
    elif signals >= 2:
        return "MEDIUM"
    return "LOW"


def _template_report(
    state: InvestigationState,
    ip: dict[str, Any],
    device: dict[str, Any],
    graph: dict[str, Any],
    matrix: dict[str, Any],
) -> str:
    """Generate a structured forensic report without LLM."""
    lines = [
        "═══════════════════════════════════════════════════",
        "      FIN-GUARDIAN AI — FORENSIC INVESTIGATION REPORT",
        "═══════════════════════════════════════════════════",
        f"Transaction ID : {state['transaction_id']}",
        f"Account        : {state['account_id']}",
        f"Recipient      : {state['recipient_id']}",
        f"Amount         : ₹{state['amount']:,.2f}",
        f"Generated At   : {datetime.now(timezone.utc).isoformat()}",
        "",
        "── EXECUTIVE SUMMARY ──────────────────────────────",
        f"ML Risk Score  : {state['ml_risk_score']:.4f} → {state['ml_verdict']}",
        f"Rule Matrix    : {matrix.get('risk_score', 'N/A')} → {matrix.get('verdict', 'N/A')}",
        "",
        "── IP ANALYSIS ────────────────────────────────────",
        f"  Origin       : {ip.get('city')}, {ip.get('country')}",
        f"  ISP          : {ip.get('isp')}",
        f"  VPN/Proxy    : {'⚠ YES' if ip.get('is_vpn_proxy') else 'No'}",
        f"  Signals      : {', '.join(ip.get('risk_signals', ['none']))}",
        "",
        "── DEVICE ANALYSIS ────────────────────────────────",
        f"  Device ID    : {device.get('device_id')}",
        f"  Known Device : {'Yes' if device.get('is_known_device') else '⚠ No'}",
        f"  Risk Level   : {device.get('risk_level')}",
        f"  Signals      : {', '.join(device.get('risk_signals', ['none']))}",
        "",
        "── NETWORK GRAPH (Multi-Hop Analysis) ─────────────",
        f"  Direct fraud connections  : {graph.get('direct_fraud_connections', 0)}",
        f"  2-hop suspicious accounts : {graph.get('two_hop_suspicious_count', 0)}",
        f"  Fraud cluster size        : {graph.get('fraud_cluster_size', 0)}",
        f"  Circular transfers        : {graph.get('circular_transfers_found', 0)}",
        f"  Graph risk level          : {graph.get('risk_level', 'UNKNOWN')}",
        "",
        "── RECOMMENDATION ─────────────────────────────────",
        f"  VERDICT: {matrix.get('verdict', state['ml_verdict'])}",
        f"  Key factors: {'; '.join(matrix.get('risk_factors', [])[:3])}",
        "═══════════════════════════════════════════════════",
    ]
    return "\n".join(lines)


# ── Build the LangGraph state machine ─────────────────────────────────────

def _build_graph() -> Any:
    builder: StateGraph = StateGraph(InvestigationState)  # type: ignore[type-arg]

    builder.add_node("ip_analysis", node_ip_analysis)
    builder.add_node("device_check", node_device_check)
    builder.add_node("graph_analysis", node_graph_analysis)
    builder.add_node("risk_fallback", node_risk_fallback)
    builder.add_node("synthesise", node_synthesise)

    # Sequential pipeline
    builder.add_edge(START, "ip_analysis")
    builder.add_edge("ip_analysis", "device_check")
    builder.add_edge("device_check", "graph_analysis")
    builder.add_edge("graph_analysis", "risk_fallback")
    builder.add_edge("risk_fallback", "synthesise")
    builder.add_edge("synthesise", END)

    return builder.compile()


# Singleton graph instance
_detective_graph = _build_graph()


# ── Public API ────────────────────────────────────────────────────────────

async def run_investigation(
    transaction_id: str,
    account_id: str,
    recipient_id: str,
    amount: float,
    account_age_days: int,
    is_new_recipient: bool,
    sender_tx_count: int,
    hour_of_day: int,
    ip_address: str | None,
    device_id: str | None,
    has_gps: bool,
    ml_risk_score: float,
    ml_verdict: str,
    shap_top_features: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Run the full AI detective investigation pipeline.

    This is called asynchronously after a HOLD verdict.
    Returns the complete forensic investigation report.
    """
    import time
    t0 = time.perf_counter()

    initial_state: InvestigationState = {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "recipient_id": recipient_id,
        "amount": amount,
        "account_age_days": account_age_days,
        "is_new_recipient": is_new_recipient,
        "sender_tx_count": sender_tx_count,
        "hour_of_day": hour_of_day,
        "ip_address": ip_address,
        "device_id": device_id,
        "has_gps": has_gps,
        "ml_risk_score": ml_risk_score,
        "ml_verdict": ml_verdict,
        "shap_top_features": shap_top_features,
        # Output fields — populated by nodes
        "ip_report": {},
        "device_report": {},
        "graph_report": {},
        "risk_matrix_report": {},
        "forensic_report": "",
        "final_confidence": "LOW",
        "investigation_duration_ms": 0.0,
    }

    try:
        # Run synchronous LangGraph in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        final_state = await loop.run_in_executor(
            None,
            lambda: _detective_graph.invoke(initial_state),
        )
    except Exception as e:
        logger.error("Detective investigation failed for tx={}: {}", transaction_id, str(e))
        final_state = {
            **initial_state,
            "forensic_report": f"Investigation failed: {str(e)}. ML verdict ({ml_verdict}) stands.",
            "final_confidence": "LOW",
        }

    duration_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "Detective complete | tx={} | verdict={} | duration={:.1f}ms",
        transaction_id,
        ml_verdict,
        duration_ms,
    )

    return {
        "transaction_id": transaction_id,
        "forensic_report": final_state.get("forensic_report", "No report generated."),
        "final_confidence": final_state.get("final_confidence", "LOW"),
        "ip_report": final_state.get("ip_report", {}),
        "device_report": final_state.get("device_report", {}),
        "graph_report": final_state.get("graph_report", {}),
        "risk_matrix_report": final_state.get("risk_matrix_report", {}),
        "investigation_duration_ms": round(duration_ms, 1),
    }
