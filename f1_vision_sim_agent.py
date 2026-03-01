from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from pydantic import BaseModel
import random
import re
import time
from typing import Any, Mapping

import convex_sink
from observability import (
    initialize_laminar_from_env,
    set_laminar_span_output,
    set_laminar_trace_context,
    shutdown_laminar,
    start_laminar_span,
)
from race_models import (
    CooldownState,
    EventEntities,
    EventType,
    Evidence,
    EvidenceSource,
    FlagStatus,
    NeutralizationType,
    RaceEvent,
    RaceState,
    SCHEMA_VERSION,
    Severity,
    Weather,
    WeatherCondition,
    to_active_events,
    is_jsonschema_available,
    validate_race_event,
    validate_race_state,
)


DEFAULT_STREAM_URL = "http://127.0.0.1:5173"
DEFAULT_OUTPUT_PATH = ".context/f1_vision_emissions.ndjson"


EVENT_SEVERITY_DEFAULTS: dict[EventType, Severity] = {
    EventType.OVERTAKE: Severity.LOW,
    EventType.YELLOW_FLAG: Severity.MEDIUM,
    EventType.SAFETY_CAR: Severity.HIGH,
    EventType.VSC: Severity.MEDIUM,
    EventType.PIT_STOP: Severity.INFO,
    EventType.CRASH: Severity.HIGH,
    EventType.SPIN: Severity.MEDIUM,
    EventType.TRACK_LIMITS: Severity.LOW,
    EventType.WEATHER_SHIFT: Severity.MEDIUM,
    EventType.RETIREMENT: Severity.HIGH,
    EventType.FASTEST_LAP: Severity.INFO,
}


FLAG_PRIORITY: dict[FlagStatus, int] = {
    FlagStatus.RED: 6,
    FlagStatus.SAFETY_CAR: 5,
    FlagStatus.DOUBLE_YELLOW: 4,
    FlagStatus.YELLOW: 3,
    FlagStatus.VSC: 2,
    FlagStatus.CHEQUERED: 1,
    FlagStatus.GREEN: 0,
}


ACTIVE_EVENT_DEDUPE_BUCKET_S = 30.0


@dataclass(slots=True)
class VisionRuntimeConfig:
    stream_url: str = field(default_factory=lambda: os.getenv("STREAM_URL", DEFAULT_STREAM_URL))
    session_id: str = field(
        default_factory=lambda: os.getenv("F1_SESSION_ID", f"f1_stream_{datetime.now(timezone.utc):%Y%m%d}")
    )
    tick_interval_s: float = field(default_factory=lambda: float(os.getenv("VISION_TICK_SECONDS", "7")))
    tick_jitter_s: float = field(default_factory=lambda: float(os.getenv("VISION_TICK_JITTER_SECONDS", "1")))
    state_confidence_threshold: float = field(
        default_factory=lambda: float(os.getenv("VISION_STATE_CONFIDENCE_THRESHOLD", "0.55"))
    )
    min_event_confidence: float = field(default_factory=lambda: float(os.getenv("VISION_MIN_EVENT_CONFIDENCE", "0.6")))
    active_event_horizon_s: float = field(default_factory=lambda: float(os.getenv("VISION_EVENT_HORIZON_SECONDS", "120")))
    validate_contracts: bool = field(
        default_factory=lambda: os.getenv("VISION_VALIDATE_CONTRACTS", "1").strip() not in {"0", "false", "False"}
    )
    output_path: str = field(default_factory=lambda: os.getenv("VISION_OUTPUT_PATH", DEFAULT_OUTPUT_PATH))
    browser_use_timeout_s: float = field(default_factory=lambda: float(os.getenv("VISION_BROWSER_USE_TIMEOUT", "45")))
    browser_use_max_steps: int = field(default_factory=lambda: int(os.getenv("VISION_BROWSER_USE_MAX_STEPS", "5")))


@dataclass(slots=True)
class RuntimeSession:
    session_id: str
    active_events: list[RaceEvent] = field(default_factory=list)
    previous_state: RaceState | None = None
    last_neutralization: NeutralizationType = NeutralizationType.NONE
    last_green_from_yellow_or_vsc_at: datetime | None = None
    last_safety_car_restart_at: datetime | None = None


# ---------------------------------------------------------------------------
# Pydantic output-schema models for the Browser Use Cloud structured output.
# These must match the dict shape consumed by _build_race_events() downstream.
# ---------------------------------------------------------------------------

class _EvidenceOut(BaseModel):
    source: str | None = None
    start_s: float | None = None
    end_s: float | None = None
    summary: str | None = None
    frame_refs: list[str] | None = None


class _EntitiesOut(BaseModel):
    drivers: list[str] | None = None
    teams: list[str] | None = None
    car_numbers: list[int] | None = None
    lap: int | None = None
    sector: int | None = None
    location: str | None = None


class _RaceEventOut(BaseModel):
    event_type: str
    severity: str | None = None
    confidence: float = 0.0
    timestamp_s: float | None = None
    evidence: _EvidenceOut | None = None
    entities: _EntitiesOut | None = None


class _WeatherOut(BaseModel):
    condition: str | None = None
    track_temp_c: float | None = None
    air_temp_c: float | None = None
    precipitation_pct: float | None = None
    wind_kph: float | None = None


class _FrameAnalysis(BaseModel):
    frame_time_s: float | None = None
    lap: int | None = None
    flag_status: str | None = None
    weather: _WeatherOut | None = None
    state_confidence: float = 0.0
    events: list[_RaceEventOut] = []


# ---------------------------------------------------------------------------

class BrowserUseFrameAnalyzer:
    """Calls Browser Use Cloud to take a screenshot of the live stream and
    return a contract-valid frame analysis dict on every tick."""

    def __init__(self, config: VisionRuntimeConfig) -> None:
        self.config = config
        self._session_id: str | None = None

    def analyze_frame(self) -> dict[str, Any]:
        prompt = self._build_prompt()
        with start_laminar_span(
            name="vision.analyze_frame",
            span_type="LLM",
            input_payload={
                "stream_url": self.config.stream_url,
                "model": "browser-use-cloud",
            },
            metadata={
                "session_id": self.config.session_id,
                "component": "browser_use_analyzer",
            },
            tags=["pipeline:f1_replay", "component:vision", "stage:detection"],
            attributes={
                "vision.timeout_s": self.config.browser_use_timeout_s,
                "vision.max_steps": self.config.browser_use_max_steps,
            },
        ):
            set_laminar_trace_context(
                session_id=self.config.session_id,
                metadata={
                    "stream_url": self.config.stream_url,
                    "component": "vision_loop",
                },
            )
            try:
                result = asyncio.run(self._async_analyze_frame(prompt))
                result.setdefault("state_confidence", 0.0)
                result.setdefault("events", [])
                set_laminar_span_output(
                    output={
                        "status": "ok",
                        "state_confidence": result.get("state_confidence", 0.0),
                        "event_count": len(result.get("events", [])),
                    },
                    tags=["status:ok", "stage:detection"],
                )
                return result
            except Exception as exc:  # fail closed to NO_BET-friendly state
                diagnostic = f"browser_use_cloud_error: {type(exc).__name__}: {exc}"
                import sys
                print(diagnostic, file=sys.stderr, flush=True)
                set_laminar_span_output(
                    output={"status": "error", "diagnostic": diagnostic},
                    tags=["status:error", "stage:detection"],
                )
                return {
                    "state_confidence": 0.0,
                    "events": [],
                    "diagnostic": diagnostic,
                }

    async def _async_analyze_frame(self, prompt: str) -> dict[str, Any]:
        try:
            from browser_use_sdk import AsyncBrowserUse  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "browser-use-sdk is required: pip install browser-use-sdk"
            ) from exc

        api_key = os.getenv("BROWSER_USE_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "BROWSER_USE_API_KEY is required for Browser Use Cloud analysis"
            )

        async with AsyncBrowserUse(api_key=api_key) as client:
            if self._session_id is None:
                session = await client.sessions.create(
                    start_url=self.config.stream_url,
                    keep_alive=True,
                )
                self._session_id = str(session.id)

            task_run = client.run(
                prompt,
                session_id=self._session_id,
                vision=True,
                schema=_FrameAnalysis,
                max_steps=self.config.browser_use_max_steps,
                system_prompt_extension=(
                    "If you see a browser warning, ngrok interstitial, or a page asking you "
                    "to 'Visit Site' or 'Accept', click through it to reach the actual website "
                    "before doing anything else."
                ),
            )

            async def _await() -> Any:
                return await task_run

            task_result = await asyncio.wait_for(
                _await(), timeout=self.config.browser_use_timeout_s
            )

        if task_result.output is None:
            return {"state_confidence": 0.0, "events": []}
        return task_result.output.model_dump()

    def stop(self) -> None:
        """Stop the persistent cloud browser session. Call on shutdown."""
        if self._session_id is None:
            return
        session_id = self._session_id
        self._session_id = None
        try:
            asyncio.run(self._async_stop_session(session_id))
        except Exception:
            pass

    async def _async_stop_session(self, session_id: str) -> None:
        try:
            from browser_use_sdk import AsyncBrowserUse  # type: ignore
        except ImportError:
            return
        api_key = os.getenv("BROWSER_USE_API_KEY", "").strip()
        if not api_key:
            return
        async with AsyncBrowserUse(api_key=api_key) as client:
            await client.sessions.stop(session_id)

    def _build_prompt(self) -> str:
        return (
            "Take a screenshot of the current F1 race replay video frame. "
            "Analyze only what is clearly visible right now. Identify:\n"
            "- frame_time_s: video timestamp in seconds\n"
            "- lap: current lap number\n"
            "- flag_status: one of GREEN, YELLOW, DOUBLE_YELLOW, RED, SAFETY_CAR, VSC, CHEQUERED\n"
            "- weather: condition (CLEAR/CLOUDY/LIGHT_RAIN/HEAVY_RAIN/MIXED), temperatures, "
            "precipitation percentage, wind speed\n"
            "- state_confidence: how clearly the frame is readable (0.0–1.0)\n"
            "- events: any visible race events from this list only — "
            "OVERTAKE, YELLOW_FLAG, SAFETY_CAR, VSC, PIT_STOP, CRASH, SPIN, "
            "TRACK_LIMITS, WEATHER_SHIFT, RETIREMENT, FASTEST_LAP\n\n"
            "Rules:\n"
            "- Do not hallucinate. Only report what is clearly visible.\n"
            "- If uncertain, lower state_confidence and event confidence values.\n"
            "- If no supported event is visible, return an empty events list."
        )

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        """Parse a JSON object from raw text, stripping markdown fences if present."""
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            return json.loads(text[start : end + 1])


def _safe_enum(enum_cls: type[Any], value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return enum_cls(value)
    except Exception:
        return default


def _float_or(default: float, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_or(default: int, value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _as_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _primary_entity_key(entities: EventEntities) -> str:
    if entities.car_numbers:
        return str(min(entities.car_numbers))
    if entities.drivers:
        return sorted(entities.drivers)[0]
    return "NA"


def _event_id(timestamp_s: float, event_type: EventType, entities: EventEntities) -> str:
    timestamp_ms_rounded = int(round(max(0.0, timestamp_s) * 1000.0))
    return f"evt_{timestamp_ms_rounded}_{event_type.value}_{_primary_entity_key(entities)}"


def _best_candidate(existing: RaceEvent | None, candidate: RaceEvent) -> RaceEvent:
    if existing is None:
        return candidate
    if candidate.confidence > existing.confidence:
        return candidate
    if candidate.confidence < existing.confidence:
        return existing
    if candidate.timestamp_s < existing.timestamp_s:
        return candidate
    if candidate.timestamp_s > existing.timestamp_s:
        return existing
    return candidate if candidate.event_id < existing.event_id else existing


def _parse_entities(raw: Mapping[str, Any], fallback_lap: int | None) -> EventEntities:
    drivers = [item.strip() for item in _as_items(raw.get("drivers")) if isinstance(item, str) and item.strip()] or None
    teams = [item.strip() for item in _as_items(raw.get("teams")) if isinstance(item, str) and item.strip()] or None

    car_numbers: list[int] = []
    for item in _as_items(raw.get("car_numbers")):
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 99:
            car_numbers.append(number)

    lap = raw.get("lap")
    lap_value = max(0, fallback_lap) if fallback_lap is not None else None
    if lap is not None:
        parsed_lap = _int_or_none(lap)
        if parsed_lap is not None:
            lap_value = max(0, parsed_lap)

    sector = raw.get("sector")
    sector_value = None
    if sector is not None:
        sector_int = _int_or_none(sector)
        if sector_int is None:
            sector_int = 0
        if 1 <= sector_int <= 3:
            sector_value = sector_int

    location_raw = raw.get("location")
    location = location_raw.strip() if isinstance(location_raw, str) and location_raw.strip() else None
    return EventEntities(
        drivers=drivers,
        teams=teams,
        car_numbers=sorted(set(car_numbers)) or None,
        lap=lap_value,
        sector=sector_value,
        location=location,
    )


def _parse_weather(raw_weather: Mapping[str, Any] | None, previous: Weather | None) -> Weather:
    if raw_weather is None:
        return previous or Weather(
            condition=WeatherCondition.MIXED,
            track_temp_c=0.0,
            air_temp_c=0.0,
            precipitation_pct=0.0,
            wind_kph=0.0,
        )

    condition = _safe_enum(
        WeatherCondition,
        raw_weather.get("condition") if raw_weather else None,
        previous.condition if previous else WeatherCondition.MIXED,
    )
    track_temp_c = _float_or(previous.track_temp_c if previous else 0.0, raw_weather.get("track_temp_c"))
    air_temp_c = _float_or(previous.air_temp_c if previous else 0.0, raw_weather.get("air_temp_c"))
    precipitation_pct = _clamp(
        _float_or(previous.precipitation_pct if previous else 0.0, raw_weather.get("precipitation_pct")),
        0.0,
        100.0,
    )
    wind_kph = max(0.0, _float_or(previous.wind_kph if previous else 0.0, raw_weather.get("wind_kph")))
    return Weather(
        condition=condition,
        track_temp_c=track_temp_c,
        air_temp_c=air_temp_c,
        precipitation_pct=precipitation_pct,
        wind_kph=wind_kph,
    )


def _resolve_flag_status(
    raw_flag: Any,
    events: list[RaceEvent],
    previous_state: RaceState | None,
) -> FlagStatus:
    parsed = _safe_enum(FlagStatus, raw_flag, None)
    if parsed is not None:
        return parsed

    event_implied: list[FlagStatus] = []
    for event in events:
        if event.event_type == EventType.SAFETY_CAR:
            event_implied.append(FlagStatus.SAFETY_CAR)
        elif event.event_type == EventType.YELLOW_FLAG:
            event_implied.append(FlagStatus.YELLOW)
        elif event.event_type == EventType.VSC:
            event_implied.append(FlagStatus.VSC)

    if event_implied:
        return sorted(event_implied, key=lambda flag: FLAG_PRIORITY[flag], reverse=True)[0]

    if previous_state:
        return previous_state.flag_status

    return FlagStatus.GREEN


def _flag_to_neutralization(flag_status: FlagStatus) -> NeutralizationType:
    if flag_status in {FlagStatus.YELLOW, FlagStatus.DOUBLE_YELLOW}:
        return NeutralizationType.YELLOW_FLAG
    if flag_status == FlagStatus.VSC:
        return NeutralizationType.VSC
    if flag_status == FlagStatus.SAFETY_CAR:
        return NeutralizationType.SAFETY_CAR
    return NeutralizationType.NONE


def _age_seconds(now: datetime, then: datetime | None) -> float | None:
    if then is None:
        return None
    return round((now - then).total_seconds(), 3)


def _build_cooldown_state(
    now: datetime,
    flag_status: FlagStatus,
    session: RuntimeSession,
) -> CooldownState:
    previous_flag = session.previous_state.flag_status if session.previous_state else None

    current_neutralization = _flag_to_neutralization(flag_status)
    if current_neutralization != NeutralizationType.NONE:
        session.last_neutralization = current_neutralization

    if previous_flag in {FlagStatus.YELLOW, FlagStatus.DOUBLE_YELLOW, FlagStatus.VSC} and flag_status == FlagStatus.GREEN:
        session.last_green_from_yellow_or_vsc_at = now

    if previous_flag == FlagStatus.SAFETY_CAR and flag_status == FlagStatus.GREEN:
        session.last_safety_car_restart_at = now

    return CooldownState(
        last_neutralization=session.last_neutralization,
        seconds_since_green_from_yellow_or_vsc=_age_seconds(now, session.last_green_from_yellow_or_vsc_at),
        seconds_since_safety_car_restart=_age_seconds(now, session.last_safety_car_restart_at),
    )


def _build_race_events(
    analysis: Mapping[str, Any],
    min_confidence: float,
    fallback_lap: int | None,
) -> list[RaceEvent]:
    frame_time_s = max(0.0, _float_or(0.0, analysis.get("frame_time_s")))
    deduped: dict[tuple[str, int, int, str], RaceEvent] = {}

    raw_events = analysis.get("events")
    if not isinstance(raw_events, list):
        return []

    for item in raw_events:
        if not isinstance(item, Mapping):
            continue

        event_type = _safe_enum(EventType, item.get("event_type"), None)
        if event_type is None:
            continue

        confidence = _clamp(_float_or(0.0, item.get("confidence")), 0.0, 1.0)
        if confidence < min_confidence:
            continue

        raw_entities = item.get("entities") if isinstance(item.get("entities"), Mapping) else {}
        entities = _parse_entities(raw_entities, fallback_lap)

        timestamp_s = max(0.0, _float_or(frame_time_s, item.get("timestamp_s")))
        evidence_raw = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
        evidence_source = _safe_enum(EvidenceSource, evidence_raw.get("source"), EvidenceSource.VISION)
        evidence_start = max(0.0, _float_or(timestamp_s, evidence_raw.get("start_s")))
        evidence_end = max(evidence_start, _float_or(timestamp_s, evidence_raw.get("end_s")))

        summary = evidence_raw.get("summary") if isinstance(evidence_raw.get("summary"), str) else "Frame-level visual signal detected."
        frame_refs: list[str] | None = None
        if isinstance(evidence_raw.get("frame_refs"), list):
            refs = [str(ref) for ref in evidence_raw["frame_refs"] if isinstance(ref, str)]
            frame_refs = refs or None

        severity = _safe_enum(Severity, item.get("severity"), EVENT_SEVERITY_DEFAULTS[event_type])
        event = RaceEvent(
            schema_version=SCHEMA_VERSION,
            event_id=_event_id(timestamp_s, event_type, entities),
            timestamp_s=timestamp_s,
            event_type=event_type,
            confidence=confidence,
            evidence=Evidence(
                source=evidence_source,
                start_s=evidence_start,
                end_s=evidence_end,
                summary=summary,
                frame_refs=frame_refs,
            ),
            entities=entities,
            severity=severity,
        )

        dedupe_key = (
            event.event_type.value,
            event.entities.lap if event.entities.lap is not None else -1,
            event.entities.sector if event.entities.sector is not None else -1,
            _primary_entity_key(event.entities),
        )
        deduped[dedupe_key] = _best_candidate(deduped.get(dedupe_key), event)

    return list(deduped.values())


def _merge_active_events(
    existing: list[RaceEvent],
    new_events: list[RaceEvent],
    horizon_seconds: float,
    now_time_s: float,
) -> list[RaceEvent]:
    dedupe_bucket_s = max(5.0, min(ACTIVE_EVENT_DEDUPE_BUCKET_S, horizon_seconds / 4.0 if horizon_seconds > 0 else ACTIVE_EVENT_DEDUPE_BUCKET_S))

    def _active_event_key(event: RaceEvent) -> tuple[str, int, int, str, int]:
        bucket = int(event.timestamp_s // dedupe_bucket_s)
        return (
            event.event_type.value,
            event.entities.lap if event.entities.lap is not None else -1,
            event.entities.sector if event.entities.sector is not None else -1,
            _primary_entity_key(event.entities),
            bucket,
        )

    min_ts = max(0.0, now_time_s - horizon_seconds)
    merged: dict[tuple[str, int, int, str, int], RaceEvent] = {}
    for event in existing + new_events:
        if event.timestamp_s < min_ts:
            continue
        key = _active_event_key(event)
        merged[key] = _best_candidate(merged.get(key), event)
    return sorted(merged.values(), key=lambda event: event.timestamp_s)


def get_live_race_state(
    analyzer: BrowserUseFrameAnalyzer,
    config: VisionRuntimeConfig,
    session: RuntimeSession,
) -> tuple[RaceState, list[RaceEvent]]:
    """Analyze a live stream frame via Browser Use and emit contract-valid RaceState + RaceEvent payloads."""

    analysis = analyzer.analyze_frame()
    now = datetime.now(timezone.utc)
    tick_ts_utc = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    previous = session.previous_state
    fallback_lap = previous.lap if previous else 0
    frame_time_s = max(0.0, _float_or(0.0, analysis.get("frame_time_s")))
    state_confidence = _clamp(_float_or(0.0, analysis.get("state_confidence")), 0.0, 1.0)

    new_events = _build_race_events(analysis, config.min_event_confidence, fallback_lap=fallback_lap)

    raw_lap = analysis.get("lap")
    lap = _int_or(fallback_lap, raw_lap)
    if lap < 0:
        lap = 0

    weather_raw = analysis.get("weather") if isinstance(analysis.get("weather"), Mapping) else None
    weather = _parse_weather(weather_raw, previous.weather if previous else None)

    flag_status = _resolve_flag_status(analysis.get("flag_status"), new_events, previous)

    uncertain = state_confidence < config.state_confidence_threshold
    if uncertain:
        # Fail closed on uncertainty for emitted payloads, but preserve session continuity for recovery.
        new_events = []
        emitted_active_events: list[RaceEvent] = []
        session_active_events = _merge_active_events(
            existing=session.active_events,
            new_events=[],
            horizon_seconds=config.active_event_horizon_s,
            now_time_s=frame_time_s,
        )
        cooldown_state = None
    else:
        tracked_cooldown_state = _build_cooldown_state(now, flag_status, session)
        session_active_events = _merge_active_events(
            existing=session.active_events,
            new_events=new_events,
            horizon_seconds=config.active_event_horizon_s,
            now_time_s=frame_time_s,
        )
        emitted_active_events = session_active_events
        cooldown_state = tracked_cooldown_state

    state = RaceState(
        schema_version=SCHEMA_VERSION,
        session_id=session.session_id,
        tick_ts_utc=tick_ts_utc,
        lap=lap,
        flag_status=flag_status,
        weather=weather,
        cooldown_state=cooldown_state,
        active_events=to_active_events(emitted_active_events),
    )

    if config.validate_contracts:
        for event in new_events:
            validate_race_event(event)
        validate_race_state(state)

    session.active_events = session_active_events
    if not uncertain:
        session.previous_state = state
    return state, new_events


def _append_emission(path: str, payload: Mapping[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")


def run_loop(config: VisionRuntimeConfig, once: bool = False) -> None:
    if config.validate_contracts and not is_jsonschema_available():
        print(
            json.dumps(
                {
                    "warning": "jsonschema_not_installed",
                    "message": "Contract validation disabled at runtime; install jsonschema to enable strict checks.",
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        config.validate_contracts = False

    analyzer = BrowserUseFrameAnalyzer(config)
    session = RuntimeSession(session_id=config.session_id)

    try:
        while True:
            tick_start = time.monotonic()
            with start_laminar_span(
                name="vision.tick",
                span_type="DEFAULT",
                input_payload={"session_id": config.session_id},
                metadata={
                    "session_id": config.session_id,
                    "stream_url": config.stream_url,
                    "component": "vision_runtime",
                },
                tags=["pipeline:f1_replay", "component:vision", "stage:tick"],
                attributes={
                    "vision.tick_interval_s": config.tick_interval_s,
                    "vision.tick_jitter_s": config.tick_jitter_s,
                },
            ):
                set_laminar_trace_context(
                    session_id=config.session_id,
                    metadata={"stream_url": config.stream_url, "component": "vision_runtime"},
                )
                try:
                    state, events = get_live_race_state(analyzer, config, session)
                    envelope = {
                        "race_state": state.to_dict(),
                        "race_events": [event.to_dict() for event in events],
                    }
                    print(json.dumps(envelope, separators=(",", ":")), flush=True)
                    if config.output_path:
                        _append_emission(config.output_path, envelope)
                    convex_sink.push_race_state(envelope["race_state"])
                    for ev in envelope["race_events"]:
                        convex_sink.push_race_event(ev, session_id=config.session_id)
                    set_laminar_span_output(
                        output={
                            "status": "ok",
                            "tick_ts_utc": state.tick_ts_utc,
                            "event_count": len(events),
                        },
                        tags=["status:ok", "stage:tick"],
                    )
                except Exception as exc:
                    set_laminar_span_output(
                        output={"status": "error", "reason": f"tick_exception:{exc.__class__.__name__}"},
                        tags=["status:error", "stage:tick"],
                    )
                    raise

            if once:
                return

            elapsed = time.monotonic() - tick_start
            next_tick = max(0.2, config.tick_interval_s + random.uniform(-config.tick_jitter_s, config.tick_jitter_s) - elapsed)
            time.sleep(next_tick)
    finally:
        analyzer.stop()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="F1 Browser Use vision runtime agent")
    parser.add_argument("--once", action="store_true", help="Run one tick then exit")
    parser.add_argument("--stream-url", default=None, help="Override STREAM_URL")
    parser.add_argument("--tick-seconds", type=float, default=None, help="Override tick interval in seconds")
    parser.add_argument("--tick-jitter-seconds", type=float, default=None, help="Override cadence jitter in seconds")
    parser.add_argument("--session-id", default=None, help="Override session id")
    parser.add_argument("--no-validate", action="store_true", help="Disable schema validation")
    parser.add_argument("--output-path", default=None, help="NDJSON output file path")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = VisionRuntimeConfig()

    if args.stream_url:
        config.stream_url = args.stream_url
    if args.tick_seconds is not None:
        config.tick_interval_s = args.tick_seconds
    if args.tick_jitter_seconds is not None:
        config.tick_jitter_s = args.tick_jitter_seconds
    if args.session_id:
        config.session_id = args.session_id
    if args.no_validate:
        config.validate_contracts = False
    if args.output_path is not None:
        config.output_path = args.output_path

    initialize_laminar_from_env(
        service_name="f1_vision_sim_agent",
        metadata={"component": "vision_runtime"},
    )
    try:
        run_loop(config, once=args.once)
    finally:
        shutdown_laminar()


if __name__ == "__main__":
    main()
