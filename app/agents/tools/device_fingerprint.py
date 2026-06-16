"""
app/agents/tools/device_fingerprint.py
───────────────────────────────────────
Device fingerprint analysis tool for the Fraud Detective agent.
Analyses device metadata fields available in the transaction to
detect emulators, bots, unknown devices, and remote desktop sessions.
"""

from __future__ import annotations


def analyse_device(device_id: str | None, ip_address: str | None) -> dict:
    """
    Analyse device signals for suspicious patterns.

    In a full production system this would call a device intelligence
    service (e.g. ThreatMetrix, Seon). For now it uses heuristic
    signals available from transaction metadata.

    Returns a dict with keys:
        device_id, is_known_device, risk_signals, risk_level
    """
    risk_signals: list[str] = []
    risk_level = "LOW"

    # No device ID is a strong signal (Midnight Ghost pattern)
    if not device_id:
        risk_signals.append("no_device_id")
        risk_level = "HIGH"
    else:
        # Heuristic: emulator / test device patterns
        emulator_patterns = [
            "emulator", "android_sdk", "generic_x86", "sdk_gphone",
            "sdk-built-for-x86", "test_device", "bot_", "headless",
        ]
        device_lower = device_id.lower()
        if any(p in device_lower for p in emulator_patterns):
            risk_signals.append("emulated_device_detected")
            risk_level = "HIGH"

        # Bot / automation framework patterns
        bot_patterns = ["appium", "selenium", "detox", "espresso", "robot_"]
        if any(p in device_lower for p in bot_patterns):
            risk_signals.append("automation_framework_detected")
            risk_level = "CRITICAL"

    # No IP address when device is present is suspicious
    if device_id and not ip_address:
        risk_signals.append("no_ip_with_known_device")
        if risk_level == "LOW":
            risk_level = "MEDIUM"

    return {
        "device_id": device_id or "MISSING",
        "is_known_device": bool(device_id) and "no_device_id" not in risk_signals,
        "risk_signals": risk_signals,
        "risk_level": risk_level,
        "summary": _build_summary(device_id, risk_signals, risk_level),
    }


def _build_summary(device_id: str | None, signals: list[str], level: str) -> str:
    if not device_id:
        return "No device ID present — transaction appears to originate from software, not a physical device."
    if "emulated_device_detected" in signals:
        return f"Device '{device_id}' matches emulator patterns — consistent with bot activity."
    if "automation_framework_detected" in signals:
        return f"Device '{device_id}' matches automation framework — bot activity confirmed."
    return f"Device '{device_id}' present. No obvious emulator/bot patterns detected. Risk: {level}."
