"""Thin wrapper around the Convex Python client for pushing data from the pipeline.

Every public function is wrapped in try/except so a Convex failure never
stalls the vision loop or bet engine.  The ConvexClient is lazily
initialized from the ``CONVEX_URL`` environment variable.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_client: Any | None = None


def _get_client() -> Any:
    """Return a lazily-initialized ConvexClient, or raise if unavailable."""
    global _client
    if _client is not None:
        return _client

    url = os.environ.get("CONVEX_URL")
    if not url:
        raise RuntimeError("CONVEX_URL environment variable is not set")

    from convex import ConvexClient

    _client = ConvexClient(url)
    return _client


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def push_paper_bet(decision: dict[str, Any], bankroll_usd: float, session_id: str) -> None:
    """Push a paper-bet decision to Convex."""
    try:
        client = _get_client()
        fire_state = "FIRE" if decision.get("action") == "PLACE_BET" else "NO_FIRE"
        client.mutation("paperBets:insert", {
            "session_id": session_id,
            "schema_version": decision.get("schema_version", "1.0.0"),
            "logged_at_utc": _utc_now_iso(),
            "decision_id": decision["decision_id"],
            "event_id": decision["event_id"],
            "market_id": decision.get("market_id", ""),
            "action": decision["action"],
            "fire_state": fire_state,
            "side": decision["side"],
            "confidence": float(decision["confidence"]),
            "model_probability": float(decision["model_probability"]),
            "market_implied_probability": float(decision["market_implied_probability"]),
            "edge_pct": float(decision["edge_pct"]),
            "kelly_fraction": float(decision["kelly_fraction"]),
            "size_usd": float(decision["size_usd"]),
            "bankroll_usd": round(bankroll_usd, 2),
            "reason": decision["reason"],
        })
    except Exception:
        logger.warning("convex_sink: failed to push paper_bet", exc_info=True)


def push_race_event(event_dict: dict[str, Any], session_id: str) -> None:
    """Push a single race event to Convex."""
    try:
        client = _get_client()
        client.mutation("raceEvents:insert", {
            "session_id": session_id,
            "schema_version": event_dict.get("schema_version", "1.0.0"),
            "event_id": event_dict["event_id"],
            "timestamp_s": float(event_dict["timestamp_s"]),
            "event_type": event_dict["event_type"],
            "confidence": float(event_dict["confidence"]),
            "severity": event_dict["severity"],
            "evidence": event_dict["evidence"],
            "entities": event_dict["entities"],
        })
    except Exception:
        logger.warning("convex_sink: failed to push race_event", exc_info=True)


def push_race_state(state_dict: dict[str, Any]) -> None:
    """Push a race-state tick snapshot to Convex."""
    try:
        client = _get_client()
        args: dict[str, Any] = {
            "session_id": state_dict["session_id"],
            "schema_version": state_dict.get("schema_version", "1.0.0"),
            "tick_ts_utc": state_dict["tick_ts_utc"],
            "lap": float(state_dict["lap"]),
            "flag_status": state_dict["flag_status"],
            "weather": state_dict["weather"],
            "active_events": state_dict.get("active_events", []),
        }
        cooldown = state_dict.get("cooldown_state")
        if cooldown is not None:
            args["cooldown_state"] = cooldown
        client.mutation("raceStates:insert", args)
    except Exception:
        logger.warning("convex_sink: failed to push race_state", exc_info=True)


def push_session(session_id: str, status: str, config: dict[str, Any]) -> None:
    """Create or update a session record in Convex."""
    try:
        client = _get_client()
        now = _utc_now_iso()
        client.mutation("sessions:upsert", {
            "session_id": session_id,
            "status": status,
            "config": config,
            "updated_at_utc": now,
        })
    except Exception:
        logger.warning("convex_sink: failed to push session", exc_info=True)
