import unittest

from f1_vision_sim_agent import (
    BrowserUseFrameAnalyzer,
    RuntimeSession,
    VisionRuntimeConfig,
    _merge_active_events,
    _parse_entities,
    get_live_race_state,
)
from race_models import EventEntities, EventType, Evidence, EvidenceSource, FlagStatus, RaceEvent, Severity


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


class _SequenceAnalyzer:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = payloads
        self._index = 0

    def analyze_frame(self) -> dict:
        payload = self._payloads[self._index]
        self._index += 1
        return payload


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


class VisionAgentUncertainTickTests(unittest.TestCase):
    def test_uncertain_tick_preserves_session_active_events(self) -> None:
        analyzer = _SequenceAnalyzer(
            [
                {
                    "frame_time_s": 10.0,
                    "state_confidence": 0.95,
                    "flag_status": "GREEN",
                    "events": [
                        {
                            "event_type": "CRASH",
                            "confidence": 0.9,
                            "timestamp_s": 10.0,
                            "entities": {"car_numbers": [1], "lap": 10},
                        }
                    ],
                },
                {
                    "frame_time_s": 11.0,
                    "state_confidence": 0.1,
                    "flag_status": "GREEN",
                    "events": [],
                },
                {
                    "frame_time_s": 12.0,
                    "state_confidence": 0.95,
                    "flag_status": "GREEN",
                    "events": [],
                },
            ]
        )
        config = VisionRuntimeConfig()
        config.validate_contracts = False
        session = RuntimeSession(session_id="s")

        first_state, _ = get_live_race_state(analyzer, config, session)
        self.assertEqual(len(first_state.active_events), 1)

        second_state, second_events = get_live_race_state(analyzer, config, session)
        self.assertEqual(len(second_state.active_events), 0)
        self.assertEqual(second_events, [])
        self.assertEqual(len(session.active_events), 1)

        third_state, _ = get_live_race_state(analyzer, config, session)
        self.assertEqual(len(third_state.active_events), 1)

    def test_uncertain_transition_updates_cooldown_tracking(self) -> None:
        analyzer = _SequenceAnalyzer(
            [
                {
                    "frame_time_s": 20.0,
                    "state_confidence": 0.95,
                    "flag_status": "YELLOW",
                    "events": [],
                },
                {
                    "frame_time_s": 21.0,
                    "state_confidence": 0.1,
                    "flag_status": "GREEN",
                    "events": [],
                },
                {
                    "frame_time_s": 22.0,
                    "state_confidence": 0.95,
                    "flag_status": "GREEN",
                    "events": [],
                },
            ]
        )
        config = VisionRuntimeConfig()
        config.validate_contracts = False
        session = RuntimeSession(session_id="s")

        yellow_state, _ = get_live_race_state(analyzer, config, session)
        self.assertEqual(yellow_state.flag_status, FlagStatus.YELLOW)

        uncertain_state, _ = get_live_race_state(analyzer, config, session)
        self.assertIsNone(uncertain_state.cooldown_state)

        recovered_state, _ = get_live_race_state(analyzer, config, session)
        cooldown = recovered_state.cooldown_state
        self.assertIsNotNone(cooldown)
        if cooldown is not None:
            self.assertIsNotNone(cooldown.seconds_since_green_from_yellow_or_vsc)


if __name__ == "__main__":
    unittest.main()
