from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "1.0.0"


class EventType(str, Enum):
    OVERTAKE = "OVERTAKE"
    YELLOW_FLAG = "YELLOW_FLAG"
    SAFETY_CAR = "SAFETY_CAR"
    VSC = "VSC"
    PIT_STOP = "PIT_STOP"
    CRASH = "CRASH"
    SPIN = "SPIN"
    TRACK_LIMITS = "TRACK_LIMITS"
    WEATHER_SHIFT = "WEATHER_SHIFT"
    RETIREMENT = "RETIREMENT"
    FASTEST_LAP = "FASTEST_LAP"


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EvidenceSource(str, Enum):
    VISION = "VISION"
    OCR = "OCR"
    COMMENTARY = "COMMENTARY"
    MULTI_MODAL = "MULTI_MODAL"


class FlagStatus(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    DOUBLE_YELLOW = "DOUBLE_YELLOW"
    RED = "RED"
    SAFETY_CAR = "SAFETY_CAR"
    VSC = "VSC"
    CHEQUERED = "CHEQUERED"


class WeatherCondition(str, Enum):
    CLEAR = "CLEAR"
    CLOUDY = "CLOUDY"
    LIGHT_RAIN = "LIGHT_RAIN"
    HEAVY_RAIN = "HEAVY_RAIN"
    MIXED = "MIXED"


class NeutralizationType(str, Enum):
    NONE = "NONE"
    YELLOW_FLAG = "YELLOW_FLAG"
    VSC = "VSC"
    SAFETY_CAR = "SAFETY_CAR"


@dataclass(slots=True)
class Evidence:
    source: EvidenceSource
    start_s: float
    end_s: float
    summary: str
    frame_refs: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source.value,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "summary": self.summary,
        }
        if self.frame_refs:
            payload["frame_refs"] = list(self.frame_refs)
        return payload


@dataclass(slots=True)
class EventEntities:
    drivers: list[str] | None = None
    teams: list[str] | None = None
    car_numbers: list[int] | None = None
    lap: int | None = None
    sector: int | None = None
    location: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.drivers:
            payload["drivers"] = list(self.drivers)
        if self.teams:
            payload["teams"] = list(self.teams)
        if self.car_numbers:
            payload["car_numbers"] = list(self.car_numbers)
        if self.lap is not None:
            payload["lap"] = self.lap
        if self.sector is not None:
            payload["sector"] = self.sector
        if self.location:
            payload["location"] = self.location
        return payload


@dataclass(slots=True)
class RaceEvent:
    event_id: str
    timestamp_s: float
    event_type: EventType
    confidence: float
    evidence: Evidence
    entities: EventEntities
    severity: Severity
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "timestamp_s": self.timestamp_s,
            "event_type": self.event_type.value,
            "confidence": self.confidence,
            "evidence": self.evidence.to_dict(),
            "entities": self.entities.to_dict(),
            "severity": self.severity.value,
        }


@dataclass(slots=True)
class ActiveEvent:
    event_id: str
    event_type: EventType
    severity: Severity
    confidence: float
    timestamp_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "timestamp_s": self.timestamp_s,
        }


@dataclass(slots=True)
class Weather:
    condition: WeatherCondition
    track_temp_c: float
    air_temp_c: float
    precipitation_pct: float
    wind_kph: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition.value,
            "track_temp_c": self.track_temp_c,
            "air_temp_c": self.air_temp_c,
            "precipitation_pct": self.precipitation_pct,
            "wind_kph": self.wind_kph,
        }


@dataclass(slots=True)
class CooldownState:
    last_neutralization: NeutralizationType
    seconds_since_green_from_yellow_or_vsc: float | None
    seconds_since_safety_car_restart: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_neutralization": self.last_neutralization.value,
            "seconds_since_green_from_yellow_or_vsc": self.seconds_since_green_from_yellow_or_vsc,
            "seconds_since_safety_car_restart": self.seconds_since_safety_car_restart,
        }


@dataclass(slots=True)
class RaceState:
    session_id: str
    tick_ts_utc: str
    lap: int
    flag_status: FlagStatus
    weather: Weather
    active_events: list[ActiveEvent] = field(default_factory=list)
    cooldown_state: CooldownState | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "tick_ts_utc": self.tick_ts_utc,
            "lap": self.lap,
            "flag_status": self.flag_status.value,
            "weather": self.weather.to_dict(),
            "active_events": [event.to_dict() for event in self.active_events],
        }
        if self.cooldown_state is not None:
            payload["cooldown_state"] = self.cooldown_state.to_dict()
        return payload


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _contract_path(schema_filename: str, contracts_dir: Path | None = None) -> Path:
    base = contracts_dir if contracts_dir else Path(__file__).resolve().parent / "docs" / "contracts"
    return base / schema_filename


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_payload(payload: Mapping[str, Any], schema_filename: str, contracts_dir: Path | None = None) -> None:
    """Validate payload using JSON Schema draft 2020-12 with local ref resolution."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError(
            "jsonschema is required for contract validation. Install with: pip install jsonschema"
        ) from exc

    schema_path = _contract_path(schema_filename, contracts_dir)
    schema = _load_json(schema_path)
    resolver = jsonschema.RefResolver(base_uri=schema_path.parent.resolve().as_uri() + "/", referrer=schema)
    validator = jsonschema.Draft202012Validator(schema, resolver=resolver)
    errors = sorted(validator.iter_errors(dict(payload)), key=lambda err: list(err.path))
    if errors:
        details = "; ".join(f"{'/'.join(map(str, err.path)) or '<root>'}: {err.message}" for err in errors)
        raise ValueError(f"Payload failed {schema_filename} validation: {details}")


def is_jsonschema_available() -> bool:
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        return False
    return True


def validate_race_event(event: RaceEvent | Mapping[str, Any], contracts_dir: Path | None = None) -> None:
    payload = event.to_dict() if isinstance(event, RaceEvent) else dict(event)
    validate_payload(payload, "race_event.schema.json", contracts_dir)


def validate_race_state(state: RaceState | Mapping[str, Any], contracts_dir: Path | None = None) -> None:
    payload = state.to_dict() if isinstance(state, RaceState) else dict(state)
    validate_payload(payload, "race_state.schema.json", contracts_dir)


def to_active_events(events: Iterable[RaceEvent]) -> list[ActiveEvent]:
    return [
        ActiveEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            severity=event.severity,
            confidence=event.confidence,
            timestamp_s=event.timestamp_s,
        )
        for event in events
    ]
