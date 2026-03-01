#!/usr/bin/env python3
"""Edge + Kelly betting decision layer for RaceState -> BetDecision outputs.

This module consumes RaceState snapshots, market quotes, and model inputs to produce
schema-compatible BetDecision payloads with strict NO_BET handling.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
DEFAULT_POLICY_PATH = Path("bet_library.json")
DEFAULT_PAPER_BETS_PATH = Path("paper_bets.csv")

PAPER_BET_COLUMNS = [
    "logged_at_utc",
    "decision_id",
    "event_id",
    "market_id",
    "action",
    "fire_state",
    "side",
    "confidence",
    "model_probability",
    "market_implied_probability",
    "edge_pct",
    "kelly_fraction",
    "size_usd",
    "bankroll_usd",
    "reason",
]


@dataclass(frozen=True)
class RiskCaps:
    bankroll_usd: float
    kelly_multiplier: float = 0.5
    max_kelly_fraction: float = 0.05
    max_bankroll_pct_per_bet: float = 0.02
    max_total_exposure_pct: float = 0.20
    current_exposure_usd: float = 0.0
    max_bet_usd: float = 250.0
    min_bet_usd: float = 2.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _round2(value: float) -> float:
    return round(float(value), 2)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_decision_id(event_id: str, tick_ts_utc: str | None) -> str:
    if tick_ts_utc:
        stamp = re.sub(r"[^0-9]", "", tick_ts_utc)[:14]
    else:
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    if len(stamp) < 8:
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    safe_event = re.sub(r"[^a-zA-Z0-9_]", "_", event_id or "none")[:24]
    return f"dec_{stamp}_{safe_event}"


def _get_event_rule(event_type: str, policy: dict[str, Any]) -> dict[str, Any] | None:
    for rule in policy.get("event_type_rules", []):
        if rule.get("event_type") == event_type:
            return rule
    return None


def _severity_rank_map(policy: dict[str, Any]) -> dict[str, int]:
    ordered = (
        policy.get("decision_guardrails", {})
        .get("deterministic_replay", {})
        .get("event_priority_by_severity", ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"])
    )
    return {severity: idx for idx, severity in enumerate(ordered)}


def _select_anchor_event(race_state: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None:
    active_events = race_state.get("active_events") or []
    if not active_events:
        return None

    supported = set(policy.get("supported_event_types", []))
    severity_rank = _severity_rank_map(policy)

    candidates: list[dict[str, Any]] = []
    for event in active_events:
        if event.get("event_type") in supported:
            candidates.append(event)

    if not candidates:
        return None

    fallback_rank = len(severity_rank) + 1
    candidates.sort(
        key=lambda event: (
            severity_rank.get(str(event.get("severity")), fallback_rank),
            -float(event.get("confidence", 0.0)),
            float(event.get("timestamp_s", 0.0)),
            str(event.get("event_id", "")),
        )
    )
    return candidates[0]


def _parse_probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    if parsed < 0.0 or parsed > 1.0:
        return None
    return parsed


def _extract_market_probability(quote: dict[str, Any]) -> float | None:
    if "implied_probability" in quote:
        return _parse_probability(quote.get("implied_probability"))
    if "market_implied_probability" in quote:
        return _parse_probability(quote.get("market_implied_probability"))
    return None


def _parse_non_negative_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0.0:
        return None
    return parsed


def _parse_non_negative_int(value: Any) -> int | None:
    parsed = _parse_non_negative_float(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _is_live_quote(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value == 1:
            return True
        if value == 0:
            return False
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        return False
    if value is None:
        return False
    return False


def _select_market(
    candidate_markets: list[str],
    market_quotes: list[dict[str, Any]],
    market_priority: list[str],
) -> dict[str, Any] | None:
    if not candidate_markets or not market_quotes:
        return None

    candidate_set = set(candidate_markets)
    for market_type in market_priority:
        if market_type not in candidate_set:
            continue
        matching_live = [
            quote
            for quote in market_quotes
            if quote.get("market_type") == market_type and _is_live_quote(quote.get("is_live"))
        ]
        if not matching_live:
            continue
        matching_live.sort(key=lambda quote: str(quote.get("market_id", "")))
        return matching_live[0]
    return None


def _edge_pct(model_probability: float, market_implied_probability: float) -> float:
    return (model_probability - market_implied_probability) * 100.0


def _monitor_side(edge_pct: float, monitor_min_abs: float) -> str:
    if edge_pct >= monitor_min_abs:
        return "YES"
    if edge_pct <= -monitor_min_abs:
        return "NO"
    return "NONE"


def _place_side(edge_pct: float, place_min_abs: float) -> str:
    if edge_pct >= place_min_abs:
        return "YES"
    if edge_pct <= -place_min_abs:
        return "NO"
    return "NONE"


def _is_place_gate_satisfied(
    event_type: str,
    race_state: dict[str, Any],
    event_context: dict[str, Any],
) -> bool:
    flag_status = str(race_state.get("flag_status", ""))

    if event_type == "OVERTAKE":
        return flag_status == "GREEN" and bool(event_context.get("overtake_persisted_lap", False))
    if event_type == "VSC":
        return flag_status == "VSC" and bool(event_context.get("vsc_pit_signal_confirmed", False))
    if event_type == "PIT_STOP":
        return bool(event_context.get("pit_delta_validated", False)) and bool(
            event_context.get("traffic_projection_clean_rejoin", False)
        )
    if event_type == "CRASH":
        return bool(event_context.get("crash_durable_impact", False))
    if event_type == "SPIN":
        return bool(event_context.get("spin_recovery_not_observed", False))
    if event_type == "WEATHER_SHIFT":
        persisted_ticks = _parse_non_negative_int(event_context.get("weather_persisted_ticks"))
        return persisted_ticks is not None and persisted_ticks >= 2 and bool(
            event_context.get("strategy_alignment_confirmed", False)
        )
    if event_type == "RETIREMENT":
        return bool(event_context.get("retirement_confirmed", False))
    if event_type == "FASTEST_LAP":
        repeatable_laps = _parse_non_negative_int(event_context.get("fastest_lap_repeatable_laps"))
        return repeatable_laps is not None and repeatable_laps >= 3

    return True


def _kelly_fraction(
    side: str,
    model_probability: float,
    market_implied_probability: float,
    risk: RiskCaps,
) -> float:
    if side not in {"YES", "NO"}:
        return 0.0

    p = _clamp(model_probability, 0.0, 1.0)
    q = _clamp(market_implied_probability, 0.0, 1.0)

    if side == "YES":
        price = q
        win_prob = p
    else:
        price = 1.0 - q
        win_prob = 1.0 - p

    if price <= 0.0 or price >= 1.0:
        return 0.0

    b = (1.0 - price) / price
    if b <= 0.0:
        return 0.0

    loss_prob = 1.0 - win_prob
    raw_kelly = ((b * win_prob) - loss_prob) / b

    if raw_kelly <= 0.0:
        return 0.0

    scaled = raw_kelly * risk.kelly_multiplier
    capped = min(scaled, risk.max_kelly_fraction)
    return _round2(_clamp(capped, 0.0, 1.0))


def _size_bet_usd(kelly_fraction: float, risk: RiskCaps) -> float:
    if kelly_fraction <= 0.0:
        return 0.0

    bankroll = max(0.0, risk.bankroll_usd)
    by_kelly = bankroll * kelly_fraction
    by_single_bet_pct = bankroll * risk.max_bankroll_pct_per_bet
    remaining_total_budget = max(0.0, (bankroll * risk.max_total_exposure_pct) - risk.current_exposure_usd)

    capped = min(by_kelly, by_single_bet_pct, remaining_total_budget, risk.max_bet_usd)
    size = _round2(max(0.0, capped))

    if size < risk.min_bet_usd:
        return 0.0
    return size


def _validate_bet_decision_shape(decision: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "decision_id",
        "event_id",
        "side",
        "confidence",
        "model_probability",
        "market_implied_probability",
        "edge_pct",
        "kelly_fraction",
        "size_usd",
        "action",
        "reason",
    }
    missing = sorted(required - set(decision.keys()))
    if missing:
        raise ValueError(f"BetDecision missing required fields: {missing}")

    action = decision["action"]
    if action == "NO_BET":
        if decision["side"] != "NONE":
            raise ValueError("NO_BET must set side=NONE")
        if float(decision["size_usd"]) != 0.0:
            raise ValueError("NO_BET must set size_usd=0")
        if float(decision["kelly_fraction"]) != 0.0:
            raise ValueError("NO_BET must set kelly_fraction=0")
        if "market_id" in decision:
            raise ValueError("NO_BET must omit market_id")
    else:
        if not str(decision.get("market_id", "")).strip():
            raise ValueError(f"{action} must include market_id")


def generate_bet_decision(
    race_state: dict[str, Any],
    market_quotes: list[dict[str, Any]],
    model_probability: float,
    decision_confidence: float,
    risk: RiskCaps,
    policy: dict[str, Any],
    event_context: dict[str, Any] | None = None,
    fallback_market_probability: float = 0.5,
) -> dict[str, Any]:
    event_context = event_context or {}

    model_probability = _round2(_clamp(float(model_probability), 0.0, 1.0))
    decision_confidence = _round2(_clamp(float(decision_confidence), 0.0, 1.0))
    market_implied_probability = _round2(_clamp(float(fallback_market_probability), 0.0, 1.0))
    edge = _round2(_edge_pct(model_probability, market_implied_probability))

    monitor_conf_min = float(policy["decision_guardrails"]["decision_confidence"]["monitor_min"])
    place_conf_min = float(policy["decision_guardrails"]["decision_confidence"]["place_bet_min"])
    monitor_edge_min = float(policy["decision_guardrails"]["edge_pct"]["monitor_min_abs"])
    place_edge_min = float(policy["decision_guardrails"]["edge_pct"]["place_bet_min_abs"])
    max_quote_age_s = float(policy["decision_guardrails"]["market_data"]["max_quote_age_s"])
    min_liquidity_usd = float(policy["decision_guardrails"]["market_data"]["min_liquidity_usd"])

    event_id = "evt_none"
    market_id: str | None = None

    def no_bet(reason: str) -> dict[str, Any]:
        decision = {
            "schema_version": SCHEMA_VERSION,
            "decision_id": _build_decision_id(event_id=event_id, tick_ts_utc=race_state.get("tick_ts_utc")),
            "event_id": event_id,
            "side": "NONE",
            "confidence": decision_confidence,
            "model_probability": model_probability,
            "market_implied_probability": market_implied_probability,
            "edge_pct": edge,
            "kelly_fraction": 0,
            "size_usd": 0,
            "action": "NO_BET",
            "reason": reason,
        }
        _validate_bet_decision_shape(decision)
        return decision

    anchor = _select_anchor_event(race_state, policy)
    if not anchor:
        reason = policy.get("no_event_policy", {}).get("when_active_events_empty", {}).get(
            "reason", "No actionable events in RaceState.active_events."
        )
        return no_bet(reason)

    event_id = str(anchor.get("event_id", "evt_missing"))
    event_type = str(anchor.get("event_type", ""))

    rule = _get_event_rule(event_type, policy)
    if not rule:
        return no_bet(f"Unsupported event_type '{event_type}' for decisioning.")

    if float(anchor.get("confidence", 0.0)) < float(rule.get("min_event_confidence", 1.0)):
        return no_bet(
            f"Event confidence {anchor.get('confidence', 0.0):.2f} is below {event_type} minimum "
            f"{float(rule.get('min_event_confidence', 0.0)):.2f}."
        )

    if decision_confidence < monitor_conf_min:
        return no_bet(
            f"Decision confidence {decision_confidence:.2f} is below monitor minimum {monitor_conf_min:.2f}."
        )

    flag_status = str(race_state.get("flag_status", ""))
    if flag_status in {"RED", "DOUBLE_YELLOW"}:
        return no_bet(f"Flag status {flag_status} is hard NO_BET.")

    cooldown = race_state.get("cooldown_state")
    if not isinstance(cooldown, dict):
        reason = policy.get("fallback_behavior", {}).get("missing_cooldown_state", {}).get(
            "reason", "Cooldown metadata is missing; fail closed and flag upstream anomaly."
        )
        return no_bet(reason)

    last_neutralization = str(cooldown.get("last_neutralization", "NONE"))
    post_yellow_min = float(policy["decision_guardrails"]["cooldowns_s"]["post_green_from_yellow_or_vsc"])
    post_sc_min = float(policy["decision_guardrails"]["cooldowns_s"]["post_safety_car_restart"])

    if last_neutralization in {"YELLOW_FLAG", "VSC"}:
        since_green = cooldown.get("seconds_since_green_from_yellow_or_vsc")
        if since_green is None or float(since_green) < post_yellow_min:
            return no_bet(
                "Cooldown after YELLOW/VSC restart is below threshold "
                f"({since_green} < {post_yellow_min:.0f})."
            )

    if last_neutralization == "SAFETY_CAR":
        since_sc_restart = cooldown.get("seconds_since_safety_car_restart")
        if since_sc_restart is None or float(since_sc_restart) < post_sc_min:
            return no_bet(
                "Cooldown after SAFETY_CAR restart is below threshold "
                f"({since_sc_restart} < {post_sc_min:.0f})."
            )

    if str(rule.get("default_action")) == "NO_BET":
        reason = rule.get("no_bet_path", {}).get("reason", f"{event_type} has explicit NO_BET policy.")
        return no_bet(reason)

    market = _select_market(
        candidate_markets=list(rule.get("candidate_markets", [])),
        market_quotes=market_quotes,
        market_priority=list(policy.get("market_priority", [])),
    )
    if market is None:
        return no_bet(f"No live candidate market available for {event_type}.")

    market_id = str(market.get("market_id", ""))
    extracted_market_probability = _extract_market_probability(market)
    if extracted_market_probability is None:
        return no_bet("Market implied probability missing/invalid")
    market_implied_probability = _round2(extracted_market_probability)
    edge = _round2(_edge_pct(model_probability, market_implied_probability))

    if abs(edge) < monitor_edge_min:
        return no_bet(f"Absolute edge {abs(edge):.2f}% is below monitor threshold {monitor_edge_min:.2f}%.")

    quote_age_s = _parse_non_negative_float(market.get("quote_age_s"))
    if quote_age_s is None:
        return no_bet("Quote age missing/invalid")
    if quote_age_s > max_quote_age_s:
        return no_bet(f"Market quote age {quote_age_s:.2f}s exceeds max {max_quote_age_s:.2f}s.")

    liquidity_usd = _parse_non_negative_float(market.get("liquidity_usd"))
    if liquidity_usd is None:
        return no_bet("Market liquidity missing/invalid")
    if liquidity_usd < min_liquidity_usd:
        return no_bet(f"Market liquidity ${liquidity_usd:.2f} is below minimum ${min_liquidity_usd:.2f}.")

    place_allowed = bool(rule.get("supports_place_bet", False))
    place_gate_ok = _is_place_gate_satisfied(event_type, race_state, event_context)
    place_side = _place_side(edge, place_edge_min)

    place_eligible = (
        place_allowed
        and place_gate_ok
        and decision_confidence >= place_conf_min
        and abs(edge) >= place_edge_min
        and place_side in {"YES", "NO"}
    )

    if place_eligible:
        kelly_fraction = _kelly_fraction(place_side, model_probability, market_implied_probability, risk)
        size_usd = _size_bet_usd(kelly_fraction, risk)
        if size_usd <= 0.0:
            return no_bet("Kelly sizing is below minimum tradable size after risk caps.")

        decision = {
            "schema_version": SCHEMA_VERSION,
            "decision_id": _build_decision_id(event_id=event_id, tick_ts_utc=race_state.get("tick_ts_utc")),
            "event_id": event_id,
            "market_id": market_id,
            "side": place_side,
            "confidence": decision_confidence,
            "model_probability": model_probability,
            "market_implied_probability": market_implied_probability,
            "edge_pct": edge,
            "kelly_fraction": kelly_fraction,
            "size_usd": size_usd,
            "action": "PLACE_BET",
            "reason": "PLACE_BET thresholds passed (edge/confidence/gates) with risk-capped Kelly size.",
        }
        _validate_bet_decision_shape(decision)
        return decision

    monitor_side = _monitor_side(edge, monitor_edge_min)
    if monitor_side in {"YES", "NO"}:
        decision = {
            "schema_version": SCHEMA_VERSION,
            "decision_id": _build_decision_id(event_id=event_id, tick_ts_utc=race_state.get("tick_ts_utc")),
            "event_id": event_id,
            "market_id": market_id,
            "side": monitor_side,
            "confidence": decision_confidence,
            "model_probability": model_probability,
            "market_implied_probability": market_implied_probability,
            "edge_pct": edge,
            "kelly_fraction": 0,
            "size_usd": 0,
            "action": "MONITOR",
            "reason": "Monitor thresholds passed; PLACE_BET thresholds or event-specific gates not satisfied.",
        }
        _validate_bet_decision_shape(decision)
        return decision

    return no_bet("No action threshold passed after evaluation ladder.")


def print_terminal_block(decision: dict[str, Any], bankroll_usd: float) -> None:
    fire_state = "FIRE" if decision.get("action") == "PLACE_BET" else "NO_FIRE"

    lines = [
        "===== BET DECISION =====",
        f"FIRE_STATE: {fire_state}",
        f"ACTION: {decision['action']}",
        f"SIDE: {decision['side']}",
        f"EVENT_ID: {decision['event_id']}",
        f"MARKET_ID: {decision.get('market_id', 'N/A')}",
        f"MODEL_P: {decision['model_probability']:.2f}",
        f"MARKET_P: {decision['market_implied_probability']:.2f}",
        f"EDGE_PCT: {decision['edge_pct']:.2f}",
        f"KELLY_FRACTION: {decision['kelly_fraction']:.2f}",
        f"SIZE_USD: {decision['size_usd']:.2f}",
        f"BANKROLL_USD: {_round2(bankroll_usd):.2f}",
        f"REASON: {decision['reason']}",
        "========================",
    ]
    print("\n".join(lines))


def append_paper_bet_row(decision: dict[str, Any], bankroll_usd: float, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = (not csv_path.exists()) or csv_path.stat().st_size == 0

    fire_state = "FIRE" if decision.get("action") == "PLACE_BET" else "NO_FIRE"
    row = {
        "logged_at_utc": _utc_now_iso(),
        "decision_id": decision["decision_id"],
        "event_id": decision["event_id"],
        "market_id": decision.get("market_id", ""),
        "action": decision["action"],
        "fire_state": fire_state,
        "side": decision["side"],
        "confidence": decision["confidence"],
        "model_probability": decision["model_probability"],
        "market_implied_probability": decision["market_implied_probability"],
        "edge_pct": decision["edge_pct"],
        "kelly_fraction": decision["kelly_fraction"],
        "size_usd": decision["size_usd"],
        "bankroll_usd": _round2(bankroll_usd),
        "reason": decision["reason"],
    }

    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAPER_BET_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RaceState -> BetDecision engine")
    parser.add_argument("--race-state", required=True, type=Path, help="Path to RaceState JSON")
    parser.add_argument("--market-quotes", required=True, type=Path, help="Path to market quotes JSON array")
    parser.add_argument("--model-probability", required=True, type=float, help="Model probability for YES outcome")
    parser.add_argument("--decision-confidence", required=True, type=float, help="Decision confidence [0..1]")
    parser.add_argument("--bankroll-usd", required=True, type=float, help="Paper bankroll in USD")
    parser.add_argument("--policy-path", type=Path, default=DEFAULT_POLICY_PATH, help="Path to bet_library.json")
    parser.add_argument("--event-context", type=Path, help="Optional JSON file with event-specific gating flags")
    parser.add_argument("--output-json", type=Path, help="Optional output path for BetDecision JSON")
    parser.add_argument("--paper-bets-path", type=Path, default=DEFAULT_PAPER_BETS_PATH, help="CSV append output path")
    parser.add_argument("--fallback-market-probability", type=float, default=0.50)

    parser.add_argument("--kelly-multiplier", type=float, default=0.5)
    parser.add_argument("--max-kelly-fraction", type=float, default=0.05)
    parser.add_argument("--max-bankroll-pct-per-bet", type=float, default=0.02)
    parser.add_argument("--max-total-exposure-pct", type=float, default=0.20)
    parser.add_argument("--current-exposure-usd", type=float, default=0.0)
    parser.add_argument("--max-bet-usd", type=float, default=250.0)
    parser.add_argument("--min-bet-usd", type=float, default=2.0)

    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    race_state = _load_json(args.race_state)
    raw_quotes = _load_json(args.market_quotes)
    if isinstance(raw_quotes, dict):
        market_quotes = list(raw_quotes.get("markets", []))
    elif isinstance(raw_quotes, list):
        market_quotes = raw_quotes
    else:
        raise ValueError("--market-quotes must contain a JSON array or an object with a 'markets' array.")

    event_context: dict[str, Any] = {}
    if args.event_context:
        loaded_context = _load_json(args.event_context)
        if not isinstance(loaded_context, dict):
            raise ValueError("--event-context must be a JSON object.")
        event_context = loaded_context

    policy = _load_json(args.policy_path)

    risk = RiskCaps(
        bankroll_usd=float(args.bankroll_usd),
        kelly_multiplier=float(args.kelly_multiplier),
        max_kelly_fraction=float(args.max_kelly_fraction),
        max_bankroll_pct_per_bet=float(args.max_bankroll_pct_per_bet),
        max_total_exposure_pct=float(args.max_total_exposure_pct),
        current_exposure_usd=float(args.current_exposure_usd),
        max_bet_usd=float(args.max_bet_usd),
        min_bet_usd=float(args.min_bet_usd),
    )

    decision = generate_bet_decision(
        race_state=race_state,
        market_quotes=market_quotes,
        model_probability=float(args.model_probability),
        decision_confidence=float(args.decision_confidence),
        risk=risk,
        policy=policy,
        event_context=event_context,
        fallback_market_probability=float(args.fallback_market_probability),
    )

    print_terminal_block(decision, bankroll_usd=risk.bankroll_usd)
    append_paper_bet_row(decision, bankroll_usd=risk.bankroll_usd, csv_path=args.paper_bets_path)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(decision, indent=2), encoding="utf-8")

    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
