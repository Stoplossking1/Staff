# Observability Trace Log Format

## Purpose
This trace format gives full per-tick auditability across:
- detection (vision loop)
- decisioning (betting engine)

Every JSONL record carries correlation IDs so QA can reconstruct:
`tick_id -> event_id(s) -> decision_id`

## Log Path
- Default path: `.context/evidence/observability_trace.jsonl`
- Override with env var: `OBS_TRACE_LOG_PATH`

## Record Model
Each line is one JSON object with these top-level fields:
- `schema_version`: trace log schema version (`1.0.0`)
- `record_id`: unique observability record ID
- `recorded_at_utc`: record creation timestamp
- `record_type`: one of `tick_start`, `detection_event`, `detection_summary`, `decision_output`, `tick_end`, `error`
- `stage`: `tick`, `detection`, or `decision`
- `source`: emitting component (`vision_loop`, `betting_engine`, or caller-defined)
- `tick_ts_utc`: source tick timestamp from runtime
- `latency_ms`: measured stage latency in milliseconds
- `confidence`: confidence value for that stage/record
- `reason`: human-readable reason for action/outcome
- `correlation`: ID links

`correlation` object fields:
- `trace_id`: trace for this tick lifecycle
- `tick_id`: deterministic tick correlation ID
- `event_ids`: related event IDs for this record
- `decision_id`: related decision ID when available

### Record-Type Extensions
In addition to the common fields above, records may include `record_type`-specific top-level fields:

- `tick_start`
  - `metadata`: caller-provided tick metadata object (empty object when none supplied)

- `detection_event`
  - `event_id`: normalized event ID for this detection record
  - `event_type`: detected event type
  - `severity`: detected event severity
  - `event_index`: zero-based index of the event in the detector output
  - `payload`: normalized event payload snapshot

- `detection_summary`
  - `event_count`: number of events detected for the tick

- `decision_output`
  - `decision_id`: normalized decision ID for this decision record
  - `action`: decision action
  - `side`: decision side
  - `market_id`: market identifier when applicable
  - `payload`: normalized decision payload snapshot

- `tick_end`
  - `status`: terminal tick status (`ok` or `error`)

## Hook Integration Points
Use the wrappers from `observability.py`:

```python
from observability import (
    TraceLogger,
    instrument_vision_loop_tick,
    instrument_betting_engine_decision,
)

trace_logger = TraceLogger()

# Vision loop hook
tick_ctx, events, event_ids = instrument_vision_loop_tick(
    trace_logger,
    tick_ts_utc=race_state["tick_ts_utc"],
    detect_events=lambda: vision_detector.detect(frame),
    tick_id=race_state.get("tick_id"),  # optional if your runtime has one
)

# Betting engine hook
decision = instrument_betting_engine_decision(
    trace_logger,
    tick_ctx=tick_ctx,
    decide_bet=lambda: betting_engine.decide(race_state, market_snapshot),
    race_state=race_state,
    event_ids=event_ids,
)
```

The wrappers emit:
1. `tick_start`
2. one `detection_event` per emitted event
3. `detection_summary`
4. `decision_output`
5. `tick_end`

## A7 QA Evidence Collection
Recommended evidence workflow:
1. Run replay or deterministic sample ticks.
2. Archive `.context/evidence/observability_trace.jsonl` with test artifacts.
3. Filter by `tick_id` and verify linked `event_ids` and `decision_id`.

Example filter:

```bash
jq -c 'select(.correlation.tick_id == "tick_20260301T172213Z_000001")' .context/evidence/observability_trace.jsonl
```

## Example `decision_output` Record

```json
{
  "schema_version": "1.0.0",
  "record_id": "obs_96e72a1d6b18",
  "recorded_at_utc": "2026-03-01T17:22:14Z",
  "record_type": "decision_output",
  "stage": "decision",
  "source": "betting_engine",
  "tick_ts_utc": "2026-03-01T17:22:13Z",
  "decision_id": "dec_20260301_0090",
  "action": "MONITOR",
  "side": "YES",
  "market_id": "mkt_driver_podium_norris",
  "latency_ms": 5.214,
  "confidence": 0.88,
  "reason": "Edge is below minimum threshold after risk haircut; hold capital.",
  "payload": {
    "decision_id": "dec_20260301_0090",
    "action": "MONITOR",
    "side": "YES",
    "market_id": "mkt_driver_podium_norris",
    "confidence": 0.88,
    "reason": "Edge is below minimum threshold after risk haircut; hold capital."
  },
  "correlation": {
    "trace_id": "trace_tick_20260301T172213Z_000001",
    "tick_id": "tick_20260301T172213Z_000001",
    "event_ids": ["evt_20260301_1022"],
    "decision_id": "dec_20260301_0090"
  }
}
```
