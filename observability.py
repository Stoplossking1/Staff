"""Lightweight trace instrumentation for replay detection and decisioning.

This module is intentionally dependency-free and local-friendly:
- Emits newline-delimited JSON records for easy grep/jq workflows.
- Correlates each tick with emitted events and final decision IDs.
- Provides wrappers to hook vision and betting steps with minimal code changes.
- Supports optional Laminar forwarding through a callback sink.
"""

from __future__ import annotations

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
        ctx = TickTraceContext(
            trace_id=computed_trace_id,
            tick_id=computed_tick_id,
            tick_ts_utc=tick_ts_utc,
            source=source,
            started_ns=time.perf_counter_ns(),
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
    except Exception as exc:
        detector_latency_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3)
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
        decision = dict(decide_bet())
    except Exception as exc:
        decision_latency_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3)
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
    trace_logger.end_tick(
        tick_ctx,
        event_ids=correlated_event_ids,
        decision_id=decision_id,
        status="ok",
        reason="tick_completed",
    )
    return decision
