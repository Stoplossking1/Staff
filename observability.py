"""Lightweight trace instrumentation for replay detection and decisioning.

This module emits local JSONL traces and optionally mirrors span context/events into Laminar.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
import time
from typing import Any, Callable, Mapping, Sequence
import uuid

TRACE_LOG_SCHEMA_VERSION = "1.0.0"
DEFAULT_TRACE_LOG_PATH = ".context/evidence/observability_trace.jsonl"
LAMINAR_SERVICE_NAME = "f1_replay_pipeline"

try:
    from lmnr import Laminar  # type: ignore
    from lmnr.opentelemetry_lib.tracing.instruments import Instruments  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Laminar = None
    Instruments = None

LaminarMetadataValue = str | bool | int | float | list[str] | list[bool] | list[int] | list[float]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _elapsed_ms(start_ns: int) -> float:
    return round((time.perf_counter_ns() - start_ns) / 1_000_000.0, 3)


def _sanitize_timestamp_for_id(timestamp_utc: str) -> str:
    # Keep IDs filesystem and CLI friendly.
    return "".join(ch for ch in timestamp_utc if ch.isalnum())


@dataclass(frozen=True)
class TickTraceContext:
    trace_id: str
    tick_id: str
    tick_ts_utc: str
    source: str
    started_ns: int
    laminar_root_span: Any | None = None
    laminar_parent_span_context: Any | None = None
    laminar_trace_id: str | None = None


def _laminar_is_ready() -> bool:
    if Laminar is None:
        return False
    try:
        return bool(Laminar.is_initialized())
    except Exception:
        return False


def _coerce_laminar_value(value: Any) -> LaminarMetadataValue | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        if not value:
            return []
        if all(isinstance(item, bool) for item in value):
            return [bool(item) for item in value]
        if all(isinstance(item, int) and not isinstance(item, bool) for item in value):
            return [int(item) for item in value]
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            return [float(item) for item in value]
        if all(isinstance(item, str) for item in value):
            return [str(item) for item in value]
        return [str(item) for item in value]
    return str(value)


def _normalize_laminar_metadata(metadata: Mapping[str, Any] | None) -> dict[str, LaminarMetadataValue]:
    normalized: dict[str, LaminarMetadataValue] = {}
    if metadata is None:
        return normalized
    for key, value in metadata.items():
        if not isinstance(key, str) or not key:
            continue
        coerced = _coerce_laminar_value(value)
        if coerced is not None:
            normalized[key] = coerced
    return normalized


def _laminar_tags(*, source: str, stage: str | None = None) -> list[str]:
    tags = [
        "pipeline:f1_replay",
        f"env:{os.getenv('LMNR_ENV', 'local')}",
        f"source:{source}",
    ]
    if stage:
        tags.append(f"stage:{stage}")
    return tags


def initialize_laminar_from_env(
    *,
    service_name: str = LAMINAR_SERVICE_NAME,
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Initialize Laminar once from env vars. Returns True when active."""
    if Laminar is None:
        return False
    if _laminar_is_ready():
        return True

    project_api_key = os.getenv("LMNR_PROJECT_API_KEY", "").strip()
    if not project_api_key:
        return False

    selected_instruments: list[Any] = []
    if Instruments is not None:
        for name in ("OPENAI", "LANGCHAIN", "BROWSER_USE", "BROWSER_USE_SESSION"):
            instrument = getattr(Instruments, name, None)
            if instrument is not None:
                selected_instruments.append(instrument)

    init_metadata = _normalize_laminar_metadata(
        {
            "service": service_name,
            "environment": os.getenv("LMNR_ENV", "local"),
            **dict(metadata or {}),
        }
    )

    kwargs: dict[str, Any] = {
        "project_api_key": project_api_key,
        "metadata": init_metadata,
    }
    base_url = os.getenv("LMNR_BASE_URL", "").strip()
    if base_url:
        kwargs["base_url"] = base_url
    if selected_instruments:
        kwargs["instruments"] = selected_instruments

    try:
        Laminar.initialize(**kwargs)
        return _laminar_is_ready()
    except Exception:
        return False


def shutdown_laminar() -> None:
    """Flush + shutdown Laminar exporters for short-lived processes."""
    if not _laminar_is_ready() or Laminar is None:
        return
    try:
        Laminar.force_flush()
    except Exception:
        pass
    try:
        Laminar.shutdown()
    except Exception:
        pass


def start_laminar_span(
    *,
    name: str,
    span_type: str = "DEFAULT",
    input_payload: Any = None,
    parent_span_context: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
    tags: Sequence[str] | None = None,
    attributes: Mapping[str, Any] | None = None,
):
    """Return a Laminar span context manager, or a no-op context manager."""
    if not _laminar_is_ready() or Laminar is None:
        return nullcontext(None)

    kwargs: dict[str, Any] = {
        "name": name,
        "span_type": span_type,
        "input": input_payload,
    }
    if parent_span_context is not None:
        kwargs["parent_span_context"] = parent_span_context
    if metadata:
        kwargs["metadata"] = _normalize_laminar_metadata(metadata)
    if tags:
        kwargs["tags"] = list(tags)
    if attributes:
        kwargs["attributes"] = dict(attributes)

    try:
        return Laminar.start_as_current_span(**kwargs)
    except Exception:
        return nullcontext(None)


def set_laminar_trace_context(
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    tags: Sequence[str] | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> None:
    if not _laminar_is_ready() or Laminar is None:
        return
    try:
        if user_id:
            Laminar.set_trace_user_id(user_id)
        if session_id:
            Laminar.set_trace_session_id(session_id)
        if metadata:
            Laminar.set_trace_metadata(_normalize_laminar_metadata(metadata))
        if tags:
            Laminar.set_span_tags(list(tags))
        if attributes:
            Laminar.set_span_attributes(dict(attributes))
    except Exception:
        pass


def set_laminar_span_output(
    *,
    output: Any | None = None,
    attributes: Mapping[str, Any] | None = None,
    tags: Sequence[str] | None = None,
) -> None:
    if not _laminar_is_ready() or Laminar is None:
        return
    try:
        if output is not None:
            Laminar.set_span_output(output)
        if attributes:
            Laminar.set_span_attributes(dict(attributes))
        if tags:
            Laminar.set_span_tags(list(tags))
    except Exception:
        pass


def _start_tick_root_span(
    *,
    tick_id: str,
    tick_ts_utc: str,
    source: str,
    metadata: Mapping[str, Any] | None,
) -> tuple[Any | None, Any | None, str | None]:
    if not _laminar_is_ready() or Laminar is None:
        return None, None, None

    normalized_metadata = _normalize_laminar_metadata(metadata)
    span_metadata: dict[str, LaminarMetadataValue] = {
        "tick_id": tick_id,
        "tick_ts_utc": tick_ts_utc,
        "source": source,
        **normalized_metadata,
    }
    session_id_value = normalized_metadata.get("session_id")
    session_id = session_id_value if isinstance(session_id_value, str) else None
    user_id_value = normalized_metadata.get("user_id")
    user_id = user_id_value if isinstance(user_id_value, str) else None

    root_span: Any | None = None
    try:
        root_span = Laminar.start_span(
            name="tick.lifecycle",
            span_type="DEFAULT",
            input={"tick_id": tick_id, "tick_ts_utc": tick_ts_utc, "source": source},
            metadata=span_metadata,
            tags=_laminar_tags(source=source, stage="tick"),
            session_id=session_id,
            user_id=user_id,
            attributes={
                "tick.id": tick_id,
                "tick.source": source,
                "tick.timestamp_utc": tick_ts_utc,
            },
        )
        parent_context = Laminar.get_laminar_span_context(root_span)

        trace_id = None
        with Laminar.use_span(root_span, end_on_exit=False):
            set_laminar_trace_context(
                user_id=user_id,
                session_id=session_id,
                metadata=span_metadata,
                tags=_laminar_tags(source=source, stage="tick"),
            )
            trace_uuid = Laminar.get_trace_id()
            trace_id = str(trace_uuid) if trace_uuid is not None else None

        return root_span, parent_context, trace_id
    except Exception:
        if root_span is not None:
            try:
                root_span.end()
            except Exception:
                pass
        return None, None, None


def _finish_tick_root_span(
    ctx: TickTraceContext,
    *,
    status: str,
    reason: str,
    event_ids: Sequence[str],
    decision_id: str | None,
) -> None:
    if not _laminar_is_ready() or Laminar is None or ctx.laminar_root_span is None:
        return

    try:
        with Laminar.use_span(ctx.laminar_root_span, end_on_exit=False):
            set_laminar_span_output(
                output={
                    "status": status,
                    "reason": reason,
                    "event_ids": list(event_ids),
                    "decision_id": decision_id,
                },
                attributes={
                    "tick.status": status,
                    "tick.reason": reason,
                    "tick.event_count": len(event_ids),
                    "tick.decision_id": decision_id or "",
                },
                tags=[f"status:{status}", f"source:{ctx.source}", "stage:tick"],
            )
    except Exception:
        pass
    finally:
        try:
            ctx.laminar_root_span.end()
        except Exception:
            pass


class TraceLogger:
    """Append-only JSONL trace logger with optional Laminar forwarding."""

    def __init__(
        self,
        output_path: str | os.PathLike[str] | None = None,
        laminar_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        path = output_path or os.getenv("OBS_TRACE_LOG_PATH") or DEFAULT_TRACE_LOG_PATH
        self.output_path = Path(path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.laminar_sink = laminar_sink
        self._lock = Lock()
        self._tick_seq = 0
        self._fallback_event_seq = 0
        self._fallback_decision_seq = 0

    def begin_tick(
        self,
        tick_ts_utc: str,
        *,
        tick_id: str | None = None,
        trace_id: str | None = None,
        source: str = "vision_loop",
        metadata: Mapping[str, Any] | None = None,
    ) -> TickTraceContext:
        with self._lock:
            self._tick_seq += 1
            seq = self._tick_seq

        safe_ts = _sanitize_timestamp_for_id(tick_ts_utc)
        computed_tick_id = tick_id or f"tick_{safe_ts}_{seq:06d}"
        computed_trace_id = trace_id or f"trace_{computed_tick_id}"
        root_span, parent_context, laminar_trace_id = _start_tick_root_span(
            tick_id=computed_tick_id,
            tick_ts_utc=tick_ts_utc,
            source=source,
            metadata=metadata,
        )
        ctx = TickTraceContext(
            trace_id=computed_trace_id,
            tick_id=computed_tick_id,
            tick_ts_utc=tick_ts_utc,
            source=source,
            started_ns=time.perf_counter_ns(),
            laminar_root_span=root_span,
            laminar_parent_span_context=parent_context,
            laminar_trace_id=laminar_trace_id,
        )
        self._emit(
            {
                "record_type": "tick_start",
                "stage": "tick",
                "source": source,
                "tick_ts_utc": tick_ts_utc,
                "latency_ms": 0.0,
                "confidence": 1.0,
                "reason": "tick_ingested",
                "metadata": dict(metadata or {}),
                "laminar_trace_id": laminar_trace_id,
                "correlation": {
                    "trace_id": ctx.trace_id,
                    "tick_id": ctx.tick_id,
                    "event_ids": [],
                    "decision_id": None,
                },
            }
        )
        return ctx

    def log_detected_event(
        self,
        ctx: TickTraceContext,
        event: Mapping[str, Any],
        *,
        detector_latency_ms: float,
        reason: str | None = None,
        confidence: float | None = None,
        event_index: int | None = None,
    ) -> str:
        event_payload = dict(event)
        event_id = str(event_payload.get("event_id") or self._new_fallback_event_id(ctx.tick_id))
        event_payload["event_id"] = event_id
        computed_confidence = confidence
        if computed_confidence is None:
            value = event_payload.get("confidence")
            computed_confidence = float(value) if isinstance(value, (int, float)) else 0.0

        self._emit(
            {
                "record_type": "detection_event",
                "stage": "detection",
                "source": ctx.source,
                "tick_ts_utc": ctx.tick_ts_utc,
                "event_id": event_id,
                "event_type": event_payload.get("event_type"),
                "severity": event_payload.get("severity"),
                "event_index": event_index,
                "latency_ms": round(detector_latency_ms, 3),
                "confidence": round(computed_confidence, 4),
                "reason": reason or str(event_payload.get("reason") or "event_detected"),
                "payload": event_payload,
                "correlation": {
                    "trace_id": ctx.trace_id,
                    "tick_id": ctx.tick_id,
                    "event_ids": [event_id],
                    "decision_id": None,
                },
            }
        )
        return event_id

    def log_detection_summary(
        self,
        ctx: TickTraceContext,
        event_ids: Sequence[str],
        *,
        detector_latency_ms: float,
        reason: str = "vision_detection_complete",
    ) -> None:
        self._emit(
            {
                "record_type": "detection_summary",
                "stage": "detection",
                "source": ctx.source,
                "tick_ts_utc": ctx.tick_ts_utc,
                "event_count": len(event_ids),
                "latency_ms": round(detector_latency_ms, 3),
                "confidence": 1.0 if event_ids else 0.0,
                "reason": reason,
                "correlation": {
                    "trace_id": ctx.trace_id,
                    "tick_id": ctx.tick_id,
                    "event_ids": list(event_ids),
                    "decision_id": None,
                },
            }
        )

    def log_decision(
        self,
        ctx: TickTraceContext,
        decision: Mapping[str, Any],
        *,
        decision_latency_ms: float,
        event_ids: Sequence[str],
        reason: str | None = None,
        confidence: float | None = None,
    ) -> str:
        decision_payload = dict(decision)
        decision_id = str(decision_payload.get("decision_id") or self._new_fallback_decision_id(ctx.tick_id))
        decision_payload["decision_id"] = decision_id
        computed_confidence = confidence
        if computed_confidence is None:
            value = decision_payload.get("confidence")
            computed_confidence = float(value) if isinstance(value, (int, float)) else 0.0

        self._emit(
            {
                "record_type": "decision_output",
                "stage": "decision",
                "source": "betting_engine",
                "tick_ts_utc": ctx.tick_ts_utc,
                "decision_id": decision_id,
                "action": decision_payload.get("action"),
                "side": decision_payload.get("side"),
                "market_id": decision_payload.get("market_id"),
                "latency_ms": round(decision_latency_ms, 3),
                "confidence": round(computed_confidence, 4),
                "reason": reason or str(decision_payload.get("reason") or "decision_generated"),
                "payload": decision_payload,
                "correlation": {
                    "trace_id": ctx.trace_id,
                    "tick_id": ctx.tick_id,
                    "event_ids": list(event_ids),
                    "decision_id": decision_id,
                },
            }
        )
        return decision_id

    def end_tick(
        self,
        ctx: TickTraceContext,
        *,
        event_ids: Sequence[str],
        decision_id: str | None,
        status: str,
        reason: str,
    ) -> None:
        self._emit(
            {
                "record_type": "tick_end",
                "stage": "tick",
                "source": ctx.source,
                "tick_ts_utc": ctx.tick_ts_utc,
                "status": status,
                "latency_ms": _elapsed_ms(ctx.started_ns),
                "confidence": 1.0 if status == "ok" else 0.0,
                "reason": reason,
                "correlation": {
                    "trace_id": ctx.trace_id,
                    "tick_id": ctx.tick_id,
                    "event_ids": list(event_ids),
                    "decision_id": decision_id,
                },
            }
        )
        _finish_tick_root_span(
            ctx,
            status=status,
            reason=reason,
            event_ids=event_ids,
            decision_id=decision_id,
        )

    def log_error(
        self,
        ctx: TickTraceContext,
        *,
        stage: str,
        reason: str,
        latency_ms: float,
        event_ids: Sequence[str],
    ) -> None:
        self._emit(
            {
                "record_type": "error",
                "stage": stage,
                "source": ctx.source,
                "tick_ts_utc": ctx.tick_ts_utc,
                "latency_ms": round(latency_ms, 3),
                "confidence": 0.0,
                "reason": reason,
                "correlation": {
                    "trace_id": ctx.trace_id,
                    "tick_id": ctx.tick_id,
                    "event_ids": list(event_ids),
                    "decision_id": None,
                },
            }
        )

    def _new_fallback_event_id(self, tick_id: str) -> str:
        with self._lock:
            self._fallback_event_seq += 1
            seq = self._fallback_event_seq
        return f"{tick_id}_event_{seq:04d}"

    def _new_fallback_decision_id(self, tick_id: str) -> str:
        with self._lock:
            self._fallback_decision_seq += 1
            seq = self._fallback_decision_seq
        return f"{tick_id}_decision_{seq:04d}"

    def _emit(self, record: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "schema_version": TRACE_LOG_SCHEMA_VERSION,
            "record_id": f"obs_{uuid.uuid4().hex[:12]}",
            "recorded_at_utc": _utc_now_iso(),
            **record,
        }
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with self._lock:
            with self.output_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")

        if self.laminar_sink is not None:
            try:
                self.laminar_sink(payload)
            except Exception:
                # Observability should not break runtime behavior.
                pass


def collect_event_ids(events: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(event["event_id"]) for event in events if "event_id" in event]


def collect_event_ids_from_race_state(race_state: Mapping[str, Any]) -> list[str]:
    active_events = race_state.get("active_events")
    if not isinstance(active_events, list):
        return []
    event_ids: list[str] = []
    for item in active_events:
        if isinstance(item, Mapping) and "event_id" in item:
            event_ids.append(str(item["event_id"]))
    return event_ids


def instrument_vision_loop_tick(
    trace_logger: TraceLogger,
    *,
    tick_ts_utc: str,
    detect_events: Callable[[], Sequence[Mapping[str, Any]]],
    tick_id: str | None = None,
    trace_id: str | None = None,
    source: str = "vision_loop",
    metadata: Mapping[str, Any] | None = None,
) -> tuple[TickTraceContext, list[dict[str, Any]], list[str]]:
    """Hook point for the vision loop detector call.

    Returns the tick context plus event payloads/IDs to feed decisioning.
    """
    ctx = trace_logger.begin_tick(
        tick_ts_utc,
        tick_id=tick_id,
        trace_id=trace_id,
        source=source,
        metadata=metadata,
    )
    started_ns = time.perf_counter_ns()
    try:
        with start_laminar_span(
            name="vision.detect_events",
            span_type="LLM",
            parent_span_context=ctx.laminar_parent_span_context,
            input_payload={"tick_id": ctx.tick_id, "tick_ts_utc": ctx.tick_ts_utc},
            metadata={"trace_id": ctx.trace_id, "source": ctx.source},
            tags=_laminar_tags(source=ctx.source, stage="detection"),
            attributes={"tick.id": ctx.tick_id},
        ):
            raw_events = list(detect_events() or [])
            events: list[dict[str, Any]] = []
            for idx, item in enumerate(raw_events):
                if not isinstance(item, Mapping):
                    raise TypeError(f"detected event at index {idx} is not a mapping")
                events.append(dict(item))

            detector_latency_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3)
            event_ids: list[str] = []
            for idx, event in enumerate(events):
                event_id = trace_logger.log_detected_event(
                    ctx,
                    event,
                    detector_latency_ms=detector_latency_ms,
                    event_index=idx,
                )
                event["event_id"] = event_id
                event_ids.append(event_id)

            summary_reason = "events_detected" if event_ids else "no_events_detected"
            trace_logger.log_detection_summary(
                ctx,
                event_ids,
                detector_latency_ms=detector_latency_ms,
                reason=summary_reason,
            )
            set_laminar_span_output(
                output={
                    "status": "ok",
                    "event_count": len(event_ids),
                    "event_ids": list(event_ids),
                },
                attributes={
                    "detection.event_count": len(event_ids),
                    "detection.latency_ms": detector_latency_ms,
                },
                tags=["stage:detection", f"source:{ctx.source}"],
            )
    except Exception as exc:
        detector_latency_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3)
        set_laminar_span_output(
            output={"status": "error", "reason": f"vision_exception:{exc.__class__.__name__}"},
            attributes={"detection.latency_ms": detector_latency_ms},
            tags=["status:error", "stage:detection"],
        )
        trace_logger.log_error(
            ctx,
            stage="detection",
            reason=f"vision_exception:{exc.__class__.__name__}",
            latency_ms=detector_latency_ms,
            event_ids=[],
        )
        trace_logger.end_tick(
            ctx,
            event_ids=[],
            decision_id=None,
            status="error",
            reason="tick_failed_in_detection",
        )
        raise

    return ctx, events, event_ids


def instrument_betting_engine_decision(
    trace_logger: TraceLogger,
    *,
    tick_ctx: TickTraceContext,
    decide_bet: Callable[[], Mapping[str, Any]],
    race_state: Mapping[str, Any] | None = None,
    event_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Hook point for the betting engine decision call."""
    correlated_event_ids = list(event_ids or [])
    if not correlated_event_ids and race_state is not None:
        correlated_event_ids = collect_event_ids_from_race_state(race_state)

    started_ns = time.perf_counter_ns()
    try:
        with start_laminar_span(
            name="betting.compute_decision",
            span_type="TOOL",
            parent_span_context=tick_ctx.laminar_parent_span_context,
            input_payload={
                "tick_id": tick_ctx.tick_id,
                "event_ids": list(correlated_event_ids),
            },
            metadata={
                "trace_id": tick_ctx.trace_id,
                "source": tick_ctx.source,
                "event_count": len(correlated_event_ids),
            },
            tags=_laminar_tags(source=tick_ctx.source, stage="decision"),
            attributes={"tick.id": tick_ctx.tick_id, "decision.event_count": len(correlated_event_ids)},
        ):
            decision = dict(decide_bet())
    except Exception as exc:
        decision_latency_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3)
        set_laminar_span_output(
            output={"status": "error", "reason": f"betting_exception:{exc.__class__.__name__}"},
            attributes={"decision.latency_ms": decision_latency_ms},
            tags=["status:error", "stage:decision"],
        )
        trace_logger.log_error(
            tick_ctx,
            stage="decision",
            reason=f"betting_exception:{exc.__class__.__name__}",
            latency_ms=decision_latency_ms,
            event_ids=correlated_event_ids,
        )
        trace_logger.end_tick(
            tick_ctx,
            event_ids=correlated_event_ids,
            decision_id=None,
            status="error",
            reason="tick_failed_in_decision",
        )
        raise

    decision_latency_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3)
    decision_id = trace_logger.log_decision(
        tick_ctx,
        decision,
        decision_latency_ms=decision_latency_ms,
        event_ids=correlated_event_ids,
    )
    decision["decision_id"] = decision_id
    set_laminar_span_output(
        output={
            "status": "ok",
            "decision_id": decision_id,
            "action": decision.get("action"),
            "side": decision.get("side"),
        },
        attributes={
            "decision.latency_ms": decision_latency_ms,
            "decision.action": str(decision.get("action", "")),
            "decision.side": str(decision.get("side", "")),
        },
        tags=["status:ok", "stage:decision"],
    )
    trace_logger.end_tick(
        tick_ctx,
        event_ids=correlated_event_ids,
        decision_id=decision_id,
        status="ok",
        reason="tick_completed",
    )
    return decision
