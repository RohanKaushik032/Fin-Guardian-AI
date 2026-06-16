"""
app/agents/tools/ip_lookup.py
─────────────────────────────
IP geolocation tool for the Fraud Detective agent.
Queries the free ip-api.com service (no API key required).
Falls back gracefully if the request fails or times out.
"""

from __future__ import annotations

import httpx
from loguru import logger


def lookup_ip(ip_address: str) -> dict:
    """
    Look up geolocation and risk signals for an IP address.

    Returns a dict with keys:
        status, country, region, city, isp, is_vpn_proxy, risk_signals
    """
    if not ip_address or ip_address in ("127.0.0.1", "localhost", "::1"):
        return {
            "status": "local",
            "country": "Local",
            "region": "N/A",
            "city": "N/A",
            "isp": "Local Network",
            "is_vpn_proxy": False,
            "risk_signals": ["local_ip"],
        }

    try:
        # ip-api.com — free, no key, 45 req/min
        url = f"http://ip-api.com/json/{ip_address}?fields=status,country,regionName,city,isp,proxy,hosting,query"
        resp = httpx.get(url, timeout=3.0)
        resp.raise_for_status()
        data = resp.json()

        risk_signals: list[str] = []
        if data.get("proxy"):
            risk_signals.append("proxy_detected")
        if data.get("hosting"):
            risk_signals.append("datacenter_hosting")

        return {
            "status": data.get("status", "unknown"),
            "country": data.get("country", "Unknown"),
            "region": data.get("regionName", "Unknown"),
            "city": data.get("city", "Unknown"),
            "isp": data.get("isp", "Unknown"),
            "is_vpn_proxy": bool(data.get("proxy") or data.get("hosting")),
            "risk_signals": risk_signals,
        }

    except Exception as e:
        logger.warning("IP lookup failed for {}: {}", ip_address, str(e))
        return {
            "status": "error",
            "country": "Unknown",
            "region": "Unknown",
            "city": "Unknown",
            "isp": "Unknown",
            "is_vpn_proxy": False,
            "risk_signals": ["lookup_failed"],
        }
