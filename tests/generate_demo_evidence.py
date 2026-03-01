#!/usr/bin/env python3
"""Generate deterministic replay-to-bet demo artifacts for QA evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bet_engine import RiskCaps, generate_bet_decision
from f1_vision_sim_agent import RuntimeSession, VisionRuntimeConfig, get_live_race_state
from observability import TraceLogger, instrument_betting_engine_decision, instrument_vision_loop_tick
from race_models import is_jsonschema_available, validate_payload, validate_race_event, validate_race_state


POLICY = json.loads((ROOT / "bet_library.json").read_text(encoding="utf-8"))


class SequenceAnalyzer:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = payloads
        self._index = 0

    def analyze_frame(self) -> dict[str, Any]:
        payload = self._payloads[self._index]
        self._index += 1
        return payload


def market_quote() -> dict[str, Any]:
    return {
        "market_id": "mkt_driver_retirement_77",
        "market_type": "DRIVER_RETIREMENT",
        "is_live": True,
        "implied_probability": 0.46,
        "quote_age_s": 1.5,
        "liquidity_usd": 5000.0,
    }


def risk_caps() -> RiskCaps:
    return RiskCaps(bankroll_usd=1000.0)


def run_scenario(
    *,
    name: str,
    analysis_payload: dict[str, Any],
    event_context: dict[str, Any],
    output_dir: Path,
    strict_contracts: bool,
) -> dict[str, Any]:
    config = VisionRuntimeConfig()
    config.validate_contracts = False
    analyzer = SequenceAnalyzer([analysis_payload])
    session = RuntimeSession(session_id="qa_demo_session")
    state, events = get_live_race_state(analyzer, config, session)

    decision = generate_bet_decision(
        race_state=state.to_dict(),
        market_quotes=[market_quote()],
        model_probability=0.67,
        decision_confidence=0.9,
        risk=risk_caps(),
        policy=POLICY,
        event_context=event_context,
    )

    trace_path = output_dir / f"{name}_trace.jsonl"
    logger = TraceLogger(output_path=trace_path)
    tick_ctx, _, event_ids = instrument_vision_loop_tick(
        logger,
        tick_ts_utc=state.tick_ts_utc,
        detect_events=lambda: [event.to_dict() for event in events],
        source="qa_demo_replay",
    )
    instrument_betting_engine_decision(
        logger,
        tick_ctx=tick_ctx,
        event_ids=event_ids,
        decide_bet=lambda: decision,
    )

    race_state_path = output_dir / f"{name}_race_state.json"
    race_events_path = output_dir / f"{name}_race_events.json"
    decision_path = output_dir / f"{name}_decision.json"

    race_state_path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    race_events_path.write_text(json.dumps([event.to_dict() for event in events], indent=2), encoding="utf-8")
    decision_path.write_text(json.dumps(decision, indent=2), encoding="utf-8")

    contract_validation = "not_requested"
    if strict_contracts:
        contract_validation = "skipped_missing_jsonschema"
        if is_jsonschema_available():
            for event in events:
                validate_race_event(event)
            validate_race_state(state)
            validate_payload(decision, "bet_decision.schema.json")
            contract_validation = "passed"

    return {
        "scenario": name,
        "decision_action": decision.get("action"),
        "event_count": len(events),
        "event_ids": event_ids,
        "contract_validation": contract_validation,
        "artifacts": {
            "race_state": str(race_state_path),
            "race_events": str(race_events_path),
            "decision": str(decision_path),
            "trace": str(trace_path),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate QA demo evidence artifacts")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".context/evidence/demo"),
        help="Directory to write scenario outputs and trace logs",
    )
    parser.add_argument(
        "--strict-contracts",
        action="store_true",
        help="Attempt JSON schema validation when jsonschema dependency is available",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    weak_signal_payload = {
        "frame_time_s": 100.0,
        "state_confidence": 0.2,
        "flag_status": "GREEN",
        "events": [
            {
                "event_type": "RETIREMENT",
                "severity": "CRITICAL",
                "confidence": 0.99,
                "timestamp_s": 100.0,
                "entities": {"car_numbers": [77], "lap": 22},
            }
        ],
    }
    threshold_met_payload = {
        "frame_time_s": 120.0,
        "state_confidence": 0.95,
        "flag_status": "GREEN",
        "lap": 24,
        "weather": {
            "condition": "CLEAR",
            "track_temp_c": 32.0,
            "air_temp_c": 24.0,
            "precipitation_pct": 0,
            "wind_kph": 10.0,
        },
        "events": [
            {
                "event_type": "RETIREMENT",
                "severity": "CRITICAL",
                "confidence": 0.97,
                "timestamp_s": 120.0,
                "evidence": {
                    "source": "VISION",
                    "start_s": 119.5,
                    "end_s": 120.0,
                    "summary": "Car stopped and out of race.",
                },
                "entities": {"car_numbers": [77], "lap": 24},
            }
        ],
    }

    scenarios = [
        run_scenario(
            name="weak_signal_no_bet",
            analysis_payload=weak_signal_payload,
            event_context={"retirement_confirmed": True},
            output_dir=output_dir,
            strict_contracts=args.strict_contracts,
        ),
        run_scenario(
            name="threshold_met_place_bet",
            analysis_payload=threshold_met_payload,
            event_context={"retirement_confirmed": True},
            output_dir=output_dir,
            strict_contracts=args.strict_contracts,
        ),
    ]

    manifest_path = output_dir / "demo_manifest.json"
    manifest = {
        "generated_by": "tests/generate_demo_evidence.py",
        "strict_contracts_requested": bool(args.strict_contracts),
        "jsonschema_available": is_jsonschema_available(),
        "scenarios": scenarios,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
