import json
import tempfile
import unittest
from pathlib import Path

from observability import (
    TraceLogger,
    instrument_betting_engine_decision,
    instrument_vision_loop_tick,
)


def _read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ObservabilityTests(unittest.TestCase):
    def test_malformed_detection_payload_emits_error_and_tick_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            logger = TraceLogger(output_path=log_path)

            with self.assertRaises(TypeError):
                instrument_vision_loop_tick(
                    logger,
                    tick_ts_utc="2026-03-01T17:22:13Z",
                    detect_events=lambda: [{"event_id": "evt_ok"}, "bad_event"],
                )

            records = _read_records(log_path)
            tick_id = records[0]["correlation"]["tick_id"]
            tick_records = [record for record in records if record["correlation"]["tick_id"] == tick_id]
            tick_end_records = [record for record in tick_records if record["record_type"] == "tick_end"]
            error_records = [record for record in tick_records if record["record_type"] == "error"]

            self.assertEqual(1, len(tick_end_records))
            self.assertEqual("error", tick_end_records[0]["status"])
            self.assertEqual(1, len(error_records))
            self.assertEqual("detection", error_records[0]["stage"])

    def test_custom_source_propagates_in_detection_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            logger = TraceLogger(output_path=log_path)
            source = "replay_processor"

            instrument_vision_loop_tick(
                logger,
                tick_ts_utc="2026-03-01T17:22:13Z",
                source=source,
                detect_events=lambda: [
                    {
                        "event_id": "evt_1",
                        "event_type": "OVERTAKE",
                        "severity": "LOW",
                        "confidence": 0.7,
                    }
                ],
            )

            records = _read_records(log_path)
            detection_event = next(record for record in records if record["record_type"] == "detection_event")
            detection_summary = next(record for record in records if record["record_type"] == "detection_summary")
            tick_start = next(record for record in records if record["record_type"] == "tick_start")

            self.assertEqual(source, tick_start["source"])
            self.assertEqual(source, detection_event["source"])
            self.assertEqual(source, detection_summary["source"])

    def test_fallback_ids_match_between_logs_and_returned_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            logger = TraceLogger(output_path=log_path)

            tick_ctx, events, event_ids = instrument_vision_loop_tick(
                logger,
                tick_ts_utc="2026-03-01T17:22:13Z",
                detect_events=lambda: [{"event_type": "YELLOW_FLAG", "severity": "MEDIUM", "confidence": 0.8}],
            )
            decision = instrument_betting_engine_decision(
                logger,
                tick_ctx=tick_ctx,
                event_ids=event_ids,
                decide_bet=lambda: {
                    "action": "NO_BET",
                    "side": "NONE",
                    "confidence": 0.75,
                    "reason": "guardrail",
                },
            )

            records = _read_records(log_path)
            detection_event = next(record for record in records if record["record_type"] == "detection_event")
            decision_output = next(record for record in records if record["record_type"] == "decision_output")

            self.assertIn("event_id", events[0])
            self.assertEqual(event_ids[0], events[0]["event_id"])
            self.assertEqual(event_ids[0], detection_event["event_id"])
            self.assertEqual(event_ids[0], detection_event["payload"]["event_id"])

            self.assertIn("decision_id", decision)
            self.assertEqual(decision["decision_id"], decision_output["decision_id"])
            self.assertEqual(decision["decision_id"], decision_output["payload"]["decision_id"])


if __name__ == "__main__":
    unittest.main()
