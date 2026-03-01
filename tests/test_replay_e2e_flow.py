import json
import tempfile
import unittest
from pathlib import Path

from bet_engine import RiskCaps, generate_bet_decision
from f1_vision_sim_agent import RuntimeSession, VisionRuntimeConfig, get_live_race_state
from observability import TraceLogger, instrument_betting_engine_decision, instrument_vision_loop_tick
from race_models import is_jsonschema_available, validate_payload, validate_race_event, validate_race_state


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "bet_library.json").read_text(encoding="utf-8"))


class _SequenceAnalyzer:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = payloads
        self._index = 0

    def analyze_frame(self) -> dict:
        payload = self._payloads[self._index]
        self._index += 1
        return payload


def _read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _market_quote() -> dict:
    return {
        "market_id": "mkt_driver_retirement_77",
        "market_type": "DRIVER_RETIREMENT",
        "is_live": True,
        "implied_probability": 0.46,
        "quote_age_s": 1.5,
        "liquidity_usd": 5000.0,
    }


def _risk_caps() -> RiskCaps:
    return RiskCaps(bankroll_usd=1000.0)


class ReplayE2EFlowTests(unittest.TestCase):
    def _build_config(self) -> VisionRuntimeConfig:
        config = VisionRuntimeConfig()
        config.validate_contracts = False
        return config

    def test_weak_signal_results_in_no_bet_and_trace_linkage(self) -> None:
        analyzer = _SequenceAnalyzer(
            [
                {
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
            ]
        )
        session = RuntimeSession(session_id="qa_demo_session")
        state, new_events = get_live_race_state(analyzer, self._build_config(), session)

        self.assertEqual(new_events, [])
        self.assertEqual(state.active_events, [])
        self.assertIsNone(state.cooldown_state)

        decision = generate_bet_decision(
            race_state=state.to_dict(),
            market_quotes=[_market_quote()],
            model_probability=0.67,
            decision_confidence=0.9,
            risk=_risk_caps(),
            policy=POLICY,
            event_context={"retirement_confirmed": True},
        )

        self.assertEqual(decision["action"], "NO_BET")
        self.assertEqual(decision["side"], "NONE")
        self.assertEqual(decision["size_usd"], 0)
        self.assertIn("No actionable events", decision["reason"])

        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            logger = TraceLogger(output_path=trace_path)

            tick_ctx, events, event_ids = instrument_vision_loop_tick(
                logger,
                tick_ts_utc=state.tick_ts_utc,
                detect_events=lambda: [event.to_dict() for event in new_events],
                source="qa_demo_replay",
            )
            logged_decision = instrument_betting_engine_decision(
                logger,
                tick_ctx=tick_ctx,
                event_ids=event_ids,
                decide_bet=lambda: decision,
            )

            self.assertEqual(events, [])
            self.assertEqual(event_ids, [])
            self.assertEqual(logged_decision["action"], "NO_BET")

            records = _read_records(trace_path)
            decision_output = next(record for record in records if record["record_type"] == "decision_output")
            detection_summary = next(record for record in records if record["record_type"] == "detection_summary")
            tick_end = next(record for record in records if record["record_type"] == "tick_end")

            self.assertEqual(detection_summary["event_count"], 0)
            self.assertEqual(decision_output["action"], "NO_BET")
            self.assertEqual(decision_output["correlation"]["event_ids"], [])
            self.assertEqual(tick_end["status"], "ok")

    def test_threshold_met_results_in_place_bet_and_trace_linkage(self) -> None:
        analyzer = _SequenceAnalyzer(
            [
                {
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
            ]
        )
        session = RuntimeSession(session_id="qa_demo_session")
        state, new_events = get_live_race_state(analyzer, self._build_config(), session)
        self.assertEqual(len(new_events), 1)
        self.assertEqual(len(state.active_events), 1)
        self.assertIsNotNone(state.cooldown_state)

        decision = generate_bet_decision(
            race_state=state.to_dict(),
            market_quotes=[_market_quote()],
            model_probability=0.67,
            decision_confidence=0.9,
            risk=_risk_caps(),
            policy=POLICY,
            event_context={"retirement_confirmed": True},
        )

        self.assertEqual(decision["action"], "PLACE_BET")
        self.assertEqual(decision["side"], "YES")
        self.assertGreater(decision["size_usd"], 0.0)
        self.assertIn("market_id", decision)

        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            logger = TraceLogger(output_path=trace_path)
            event_payloads = [event.to_dict() for event in new_events]

            tick_ctx, events, event_ids = instrument_vision_loop_tick(
                logger,
                tick_ts_utc=state.tick_ts_utc,
                detect_events=lambda: event_payloads,
                source="qa_demo_replay",
            )
            logged_decision = instrument_betting_engine_decision(
                logger,
                tick_ctx=tick_ctx,
                event_ids=event_ids,
                decide_bet=lambda: decision,
            )

            self.assertEqual(len(events), 1)
            self.assertEqual(len(event_ids), 1)
            self.assertEqual(logged_decision["action"], "PLACE_BET")

            records = _read_records(trace_path)
            detection_event = next(record for record in records if record["record_type"] == "detection_event")
            decision_output = next(record for record in records if record["record_type"] == "decision_output")

            self.assertEqual(event_ids[0], detection_event["event_id"])
            self.assertEqual(event_ids, decision_output["correlation"]["event_ids"])
            self.assertEqual(decision_output["action"], "PLACE_BET")

    @unittest.skipUnless(is_jsonschema_available(), "jsonschema not installed; strict contract validation skipped")
    def test_payloads_validate_against_contract_schemas(self) -> None:
        analyzer = _SequenceAnalyzer(
            [
                {
                    "frame_time_s": 140.0,
                    "state_confidence": 0.95,
                    "flag_status": "GREEN",
                    "lap": 28,
                    "events": [
                        {
                            "event_type": "RETIREMENT",
                            "severity": "CRITICAL",
                            "confidence": 0.97,
                            "timestamp_s": 140.0,
                            "entities": {"car_numbers": [77], "lap": 28},
                        }
                    ],
                },
                {
                    "frame_time_s": 141.0,
                    "state_confidence": 0.1,
                    "flag_status": "GREEN",
                    "events": [],
                },
            ]
        )
        session = RuntimeSession(session_id="qa_demo_session")

        strong_state, strong_events = get_live_race_state(analyzer, self._build_config(), session)
        weak_state, weak_events = get_live_race_state(analyzer, self._build_config(), session)
        self.assertEqual(weak_events, [])

        place_decision = generate_bet_decision(
            race_state=strong_state.to_dict(),
            market_quotes=[_market_quote()],
            model_probability=0.67,
            decision_confidence=0.9,
            risk=_risk_caps(),
            policy=POLICY,
            event_context={"retirement_confirmed": True},
        )
        no_bet_decision = generate_bet_decision(
            race_state=weak_state.to_dict(),
            market_quotes=[_market_quote()],
            model_probability=0.67,
            decision_confidence=0.9,
            risk=_risk_caps(),
            policy=POLICY,
            event_context={"retirement_confirmed": True},
        )

        for event in strong_events:
            validate_race_event(event)
        validate_race_state(strong_state)
        validate_race_state(weak_state)
        validate_payload(place_decision, "bet_decision.schema.json")
        validate_payload(no_bet_decision, "bet_decision.schema.json")


if __name__ == "__main__":
    unittest.main()
