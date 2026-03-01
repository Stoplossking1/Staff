#!/usr/bin/env python3
"""
Paper bet pipeline — reads vision agent NDJSON from stdin, makes bet decisions
in real-time, and prints trading-terminal style output for verification against video.

Usage:
    python3 -u f1_vision_sim_agent.py | python3 -u scripts/paper_bet_loop.py
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bet_engine import RiskCaps, append_paper_bet_row, generate_bet_decision

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

POLICY_PATH    = Path("bet_library.json")
PAPER_BETS_PATH = Path("paper_bets.csv")
BANKROLL_USD   = 1_000.0

RISK = RiskCaps(
    bankroll_usd=BANKROLL_USD,
    kelly_multiplier=0.5,
    max_kelly_fraction=0.05,
    max_bankroll_pct_per_bet=0.02,
    max_total_exposure_pct=0.20,
    max_bet_usd=50.0,
    min_bet_usd=2.0,
)

# ---------------------------------------------------------------------------
# Synthetic base-rate market quotes
# These are historical averages — what the market priced BEFORE the event.
# ---------------------------------------------------------------------------

BASE_QUOTES: list[dict] = [
    {"market_id": "mkt_driver_retirement", "market_type": "DRIVER_RETIREMENT",    "is_live": True, "implied_probability": 0.08, "quote_age_s": 2.0, "liquidity_usd": 3000.0},
    {"market_id": "mkt_safety_car",        "market_type": "SAFETY_CAR_DEPLOYMENT","is_live": True, "implied_probability": 0.35, "quote_age_s": 2.0, "liquidity_usd": 4000.0},
    {"market_id": "mkt_race_winner",       "market_type": "RACE_WINNER",          "is_live": True, "implied_probability": 0.38, "quote_age_s": 2.0, "liquidity_usd": 8000.0},
    {"market_id": "mkt_podium",            "market_type": "PODIUM_FINISH",        "is_live": True, "implied_probability": 0.60, "quote_age_s": 2.0, "liquidity_usd": 3500.0},
    {"market_id": "mkt_fastest_lap",       "market_type": "FASTEST_LAP",         "is_live": True, "implied_probability": 0.12, "quote_age_s": 2.0, "liquidity_usd": 1500.0},
    {"market_id": "mkt_points_finish",     "market_type": "POINTS_FINISH",       "is_live": True, "implied_probability": 0.75, "quote_age_s": 2.0, "liquidity_usd": 2000.0},
]

MODEL_PROB: dict[str, float] = {
    "RETIREMENT":    0.92,  # retirement confirmed → very likely YES on DRIVER_RETIREMENT
    "CRASH":         0.72,  # crash visible → SC deployment much more likely than base 35%
    "SAFETY_CAR":    0.88,  # SC on screen → SAFETY_CAR_DEPLOYMENT near certain
    "VSC":           0.76,
    "YELLOW_FLAG":   0.58,
    "OVERTAKE":      0.46,  # overtake shifts win prob modestly: 38% base → ~46%
    "PIT_STOP":      0.62,
    "SPIN":          0.55,
    "WEATHER_SHIFT": 0.70,
    "FASTEST_LAP":   0.66,
    "TRACK_LIMITS":  0.50,
}

EVENT_CONTEXT: dict[str, dict] = {
    "RETIREMENT":    {"retirement_confirmed": True},
    "OVERTAKE":      {"overtake_persisted_lap": True},
    "VSC":           {"vsc_pit_signal_confirmed": True},
    "PIT_STOP":      {"pit_delta_validated": True, "traffic_projection_clean_rejoin": True},
    "CRASH":         {"crash_durable_impact": True},
    "SPIN":          {"spin_recovery_not_observed": True},
    "WEATHER_SHIFT": {"weather_persisted_ticks": 3, "strategy_alignment_confirmed": True},
    "FASTEST_LAP":   {"fastest_lap_repeatable_laps": 4},
}

# ---------------------------------------------------------------------------
# Terminal colours — force on when piped (for file output readability)
# ---------------------------------------------------------------------------

USE_COLOR = True  # always; viewer can strip if needed

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def _red(t: str) -> str:     return _c("91;1", t)
def _green(t: str) -> str:   return _c("92;1", t)
def _yellow(t: str) -> str:  return _c("93",   t)
def _cyan(t: str) -> str:    return _c("96",   t)
def _dim(t: str) -> str:     return _c("2",    t)
def _bold(t: str) -> str:    return _c("1",    t)
def _white(t: str) -> str:   return _c("97;1", t)

SEP  = "═" * 60
SEP2 = "─" * 60


def _load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _latency_ms(tick_ts_utc: str, received_ns: int) -> int:
    """Approx ms between tick timestamp and when we processed it."""
    try:
        tick_dt = datetime.fromisoformat(tick_ts_utc.replace("Z", "+00:00"))
        now_dt  = datetime.now(timezone.utc)
        return max(0, int((now_dt - tick_dt).total_seconds() * 1000))
    except Exception:
        return int((time.monotonic_ns() - received_ns) / 1_000_000)


def _extract_driver(event: dict) -> str:
    """Best-effort driver label from event_id or entities."""
    eid = event.get("event_id", "")
    parts = eid.split("_")
    if len(parts) >= 4:
        label = "_".join(parts[3:]).upper()
        if label and label not in {"NA", "NONE", ""}:
            return label
    entities = event.get("entities") or {}
    drivers = entities.get("drivers") or []
    if drivers:
        return drivers[0].upper()
    cars = entities.get("car_numbers") or []
    if cars:
        return f"#{cars[0]}"
    return "UNKNOWN"


def _ticker(etype: str, driver: str) -> str:
    mapping = {
        "RETIREMENT":    f"F1-{driver}-RETIRE",
        "CRASH":         f"F1-{driver}-CRASH",
        "SAFETY_CAR":    "F1-SC-DEPLOY",
        "VSC":           "F1-VSC-DEPLOY",
        "YELLOW_FLAG":   "F1-YELLOW-FLAG",
        "OVERTAKE":      f"F1-{driver}-PASS",
        "PIT_STOP":      f"F1-{driver}-PIT",
        "SPIN":          f"F1-{driver}-SPIN",
        "WEATHER_SHIFT": "F1-WEATHER-SHIFT",
        "FASTEST_LAP":   f"F1-{driver}-FLAP",
        "TRACK_LIMITS":  f"F1-{driver}-TL",
    }
    return mapping.get(etype, f"F1-{etype[:6]}")


def _signal_verb(action: str, side: str) -> str:
    if action == "PLACE_BET":
        return "BUY" if side == "YES" else "SELL"
    return action


def _contracts(size_usd: float, implied_prob: float) -> int:
    if implied_prob <= 0:
        return 0
    return max(1, round(size_usd / implied_prob))


def _headline(etype: str, driver: str, action: str, side: str) -> str:
    verb = _signal_verb(action, side)
    label = f"{driver} " if driver not in {"NA", "UNKNOWN"} else ""
    return f"{label}{etype.replace('_', ' ')} — {verb}!"


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def _print_hold(lap: int | str, tick_ts: str, flag: str, latency: int) -> None:
    ts = tick_ts[11:19] if len(tick_ts) >= 19 else tick_ts
    print(
        f"{_dim('●')} {_dim(f'[Lap {lap} | {ts}]')}  "
        f"{_dim('HOLD')}  {_dim('|')}  "
        f"{_dim(f'{flag} — no new signals')}  {_dim(f'|  {latency}ms')}",
        flush=True,
    )


def _print_monitor(lap: int | str, tick_ts: str, etype: str, driver: str,
                   conf: float, reason: str, latency: int) -> None:
    ts = tick_ts[11:19] if len(tick_ts) >= 19 else tick_ts
    print(
        f"{_yellow('●')} {_cyan(f'[Lap {lap} | {ts}]')}  "
        f"{_yellow('MONITOR')}  |  "
        f"{_bold(etype)} {_dim(f'({driver})')}  conf={conf:.0%}  |  {latency}ms",
        flush=True,
    )
    print(
        f"  {_dim('■')} {_yellow('HOLD')} {_bold(driver)}  |  {_dim(reason[:80])}",
        flush=True,
    )
    print(flush=True)


def _print_place_bet(
    lap: int | str,
    tick_ts: str,
    etype: str,
    driver: str,
    conf: float,
    decision: dict,
    latency: int,
) -> None:
    action     = decision["action"]
    side       = decision["side"]
    mkt_type   = decision.get("market_id", "—").replace("mkt_", "").upper()
    edge       = decision.get("edge_pct", 0.0)
    size       = decision.get("size_usd", 0.0)
    model_p    = decision.get("model_probability", 0.0)
    mkt_p      = decision.get("market_implied_probability", 0.0)
    decision_id = decision.get("decision_id", f"dec_{uuid.uuid4().hex[:12]}")
    verb       = _signal_verb(action, side)
    ticker     = _ticker(etype, driver)
    price      = mkt_p if side == "YES" else (1.0 - mkt_p)
    contracts  = _contracts(size, price)
    ts         = tick_ts[11:19] if len(tick_ts) >= 19 else tick_ts
    headline   = _headline(etype, driver, action, side)

    print(_red(SEP),                       flush=True)
    print(_white(f"🔴🔴  {headline}  🔴🔴"), flush=True)
    print(_red(SEP),                       flush=True)

    print(
        f"{_yellow('●')} {_cyan(f'[Lap {lap} | {ts}]')}  "
        f"|  latency: {latency}ms",
        flush=True,
    )
    print(
        f"  {_dim('■')} {_bold(verb)} {_bold(driver)}  |  "
        f"{_dim(etype.replace('_', ' ').title() + ' detected — conf=' + f'{conf:.0%}')}",
        flush=True,
    )
    print(flush=True)

    W = 51
    def row(label: str, value: str) -> str:
        inner = f"  {_bold(label):<14}{value}"
        return f"│{inner:<{W}}│"

    print(f"┌{'─' * W}┐",                                         flush=True)
    print(f"│  {_bold('📋  PAPER ORDER LOGGED'):<{W-1}}│",        flush=True)
    print(f"│{'─' * W}│",                                         flush=True)
    print(row("Action:",    f"{verb} {mkt_type} {side}"),          flush=True)
    print(row("Ticker:",    ticker),                                flush=True)
    print(row("Contracts:", f"{contracts}"),                        flush=True)
    print(row("Price:",     f"${price:.2f} per contract"),         flush=True)
    print(row("Total:",     f"${size:.2f}"),                       flush=True)
    print(row("Bet ID:",    decision_id[:28]),                     flush=True)
    print(row("Edge:",      f"{edge:+.1f}%  (model {model_p:.0%} vs mkt {mkt_p:.0%})"), flush=True)
    print(f"│  {'Status:':<14}{_green('✅ LOGGED'):<{W-16}}│",    flush=True)
    print(f"└{'─' * W}┘",                                         flush=True)
    print(flush=True)

    outcome = "WIN" if side == "YES" else "LOSS"
    print(
        f"→ {_bold('VERIFY:')} Watch for {_bold(driver)} {etype.replace('_', ' ')} "
        f"in video — {_green(outcome)} if confirmed",
        flush=True,
    )
    print(flush=True)


# ---------------------------------------------------------------------------
# Core tick processor
# ---------------------------------------------------------------------------

def process_tick(
    envelope: dict,
    seen_event_ids: set[str],
    policy: dict,
    received_ns: int,
) -> None:
    race_state  = envelope.get("race_state", {})
    race_events = envelope.get("race_events", [])

    tick_ts  = race_state.get("tick_ts_utc", "")
    lap      = race_state.get("lap", "?")
    flag     = race_state.get("flag_status", "?")
    latency  = _latency_ms(tick_ts, received_ns)

    new_events = [e for e in race_events if e.get("event_id") not in seen_event_ids]
    if not new_events:
        active     = race_state.get("active_events", [])
        new_events = [e for e in active if e.get("event_id") not in seen_event_ids]

    if not new_events:
        _print_hold(lap, tick_ts, flag, latency)
        return

    for event in new_events:
        eid    = event.get("event_id", "")
        etype  = str(event.get("event_type", ""))
        conf   = float(event.get("confidence", 0.0))
        driver = _extract_driver(event)
        seen_event_ids.add(eid)

        # Pass a race_state where active_events contains only this event so the
        # bet engine's anchor selection always evaluates the event we intend,
        # rather than being hijacked by a co-active SAFETY_CAR or similar.
        isolated_state = {**race_state, "active_events": [event]}

        decision = generate_bet_decision(
            race_state=isolated_state,
            market_quotes=BASE_QUOTES,
            model_probability=MODEL_PROB.get(etype, 0.5),
            decision_confidence=min(conf, 0.99),
            risk=RISK,
            policy=policy,
            event_context=EVENT_CONTEXT.get(etype, {}),
            fallback_market_probability=0.5,
        )

        action = decision.get("action", "NO_BET")
        side   = decision.get("side", "NONE")
        reason = decision.get("reason", "")

        if action == "PLACE_BET":
            _print_place_bet(lap, tick_ts, etype, driver, conf, decision, latency)
        elif action == "MONITOR":
            _print_monitor(lap, tick_ts, etype, driver, conf, reason, latency)
        else:
            ts = tick_ts[11:19] if len(tick_ts) >= 19 else tick_ts
            print(
                f"{_dim('●')} {_dim(f'[Lap {lap} | {ts}]')}  "
                f"{_dim('NO BET')}  |  "
                f"{_dim(etype + f'  ({driver})')}  "
                f"{_dim('edge=' + str(round(decision.get('edge_pct', 0.0))) + '%')}  "
                f"{_dim('|  ' + reason[:60])}",
                flush=True,
            )

        append_paper_bet_row(decision, bankroll_usd=BANKROLL_USD, csv_path=PAPER_BETS_PATH)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print(flush=True)
    print(_bold(SEP),  flush=True)
    print(_white("🏎   FORMULA ONE LIVE BETTING SIGNALS"), flush=True)
    print(_bold(SEP),  flush=True)
    print(f"  Bankroll:  ${BANKROLL_USD:,.0f}  |  Max bet: ${RISK.max_bet_usd:.0f}  |  Min edge: 3%", flush=True)
    print(_dim(SEP2),  flush=True)
    print(flush=True)

    policy = _load_policy()
    seen_event_ids: set[str] = set()

    for raw_line in sys.stdin:
        received_ns = time.monotonic_ns()
        line = raw_line.strip()
        if not line:
            continue

        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            print(_dim(f"[raw] {line[:120]}"), file=sys.stderr, flush=True)
            continue

        if "warning" in envelope and "race_state" not in envelope:
            print(_dim(f"[warn] {envelope.get('message', '')}"), flush=True)
            continue

        if "race_state" not in envelope:
            continue

        process_tick(envelope, seen_event_ids, policy, received_ns)


if __name__ == "__main__":
    main()
