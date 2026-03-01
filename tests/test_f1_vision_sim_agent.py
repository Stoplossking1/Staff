import unittest

from f1_vision_sim_agent import (
    BrowserUseFrameAnalyzer,
    _merge_active_events,
    _parse_entities,
)
from race_models import EventEntities, EventType, Evidence, EvidenceSource, RaceEvent, Severity


def _event(timestamp_s: float, *, car_number: int = 1) -> RaceEvent:
    return RaceEvent(
        event_id=f"evt_{int(timestamp_s * 1000)}_CRASH_{car_number}",
        timestamp_s=timestamp_s,
        event_type=EventType.CRASH,
        confidence=0.9,
        evidence=Evidence(
            source=EvidenceSource.VISION,
            start_s=timestamp_s,
            end_s=timestamp_s,
            summary="signal",
        ),
        entities=EventEntities(car_numbers=[car_number], lap=10),
        severity=Severity.HIGH,
    )


class VisionAgentParsingTests(unittest.TestCase):
    def test_parse_entities_accepts_scalar_fields(self) -> None:
        entities = _parse_entities(
            {"drivers": "NOR", "teams": "MCLAREN", "car_numbers": 44},
            fallback_lap=None,
        )
        self.assertEqual(entities.drivers, ["NOR"])
        self.assertEqual(entities.teams, ["MCLAREN"])
        self.assertEqual(entities.car_numbers, [44])

    def test_parse_entities_clamps_negative_lap(self) -> None:
        entities = _parse_entities({"lap": -3}, fallback_lap=None)
        self.assertEqual(entities.lap, 0)

    def test_extract_json_strips_fenced_block(self) -> None:
        payload = BrowserUseFrameAnalyzer._extract_json("```json\n{\"a\":1}\n```")
        self.assertEqual(payload, {"a": 1})


class VisionAgentMergeTests(unittest.TestCase):
    def test_merge_active_events_dedupes_same_incident_across_ticks(self) -> None:
        merged = _merge_active_events(
            existing=[_event(100.0)],
            new_events=[_event(101.0)],
            horizon_seconds=120.0,
            now_time_s=101.0,
        )
        self.assertEqual(len(merged), 1)

    def test_merge_active_events_keeps_separate_time_buckets(self) -> None:
        merged = _merge_active_events(
            existing=[_event(100.0)],
            new_events=[_event(131.0)],
            horizon_seconds=120.0,
            now_time_s=131.0,
        )
        self.assertEqual(len(merged), 2)


if __name__ == "__main__":
    unittest.main()
