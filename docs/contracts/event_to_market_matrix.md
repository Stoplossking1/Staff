# Event to Market Matrix

This matrix is the contract between event detection and market decisioning. It standardizes how each `event_type` influences market classes and expected action routing.

| event_type | Typical market impacts | Decision default | Notes |
| --- | --- | --- | --- |
| `OVERTAKE` | Race winner, podium, top-6 | `MONITOR` | Convert to `PLACE_BET` only when momentum persists for >= 1 lap and edge threshold passes. |
| `YELLOW_FLAG` | Safety car market, race winner volatility | `NO_BET` | Avoid fills during unstable pricing unless strategy explicitly targets neutralization windows. |
| `SAFETY_CAR` | Race winner, fastest lap, pit strategy derivatives | `NO_BET` | Liquidity shocks and suspended markets are common. Resume only after restart confirmation. |
| `VSC` | Race winner and pit window edges | `MONITOR` | Short-lived; require confirmation of expected pit behavior before stake. |
| `PIT_STOP` | Head-to-head, finishing position | `MONITOR` | Actionable only with validated pit delta and traffic projection. |
| `CRASH` | Driver retirement, race winner, podium | `MONITOR` | Upgrade to `PLACE_BET` if incident creates durable probability swing and markets are live. |
| `SPIN` | Head-to-head, finishing position | `MONITOR` | Often recoverable; wait for pace recovery evidence. |
| `TRACK_LIMITS` | Penalty/position props | `NO_BET` | Weak standalone signal unless repeated with steward escalation context. |
| `WEATHER_SHIFT` | Tyre strategy, race winner | `MONITOR` | Convert to `PLACE_BET` only when track condition and strategy impacts are aligned. |
| `RETIREMENT` | Race winner, podium, points finish | `PLACE_BET` | Typically high-signal if retirement is confirmed and markets remain open. |
| `FASTEST_LAP` | Fastest lap market | `MONITOR` | Limited spillover to winner markets unless paired with pace trend. |

No detected events => `active_events: []` and downstream `NO_BET` decision path.

## Valid Payload Examples

### RaceEvent example

```json
{
  "schema_version": "1.0.0",
  "event_id": "evt_20260301_00125",
  "timestamp_s": 412.34,
  "event_type": "YELLOW_FLAG",
  "confidence": 0.92,
  "evidence": {
    "source": "MULTI_MODAL",
    "start_s": 409.8,
    "end_s": 414.1,
    "summary": "Marshal panel yellow + commentary debris call",
    "frame_refs": ["frames/000412_120.jpg"]
  },
  "entities": {
    "drivers": ["NOR", "LEC"],
    "teams": ["MCLAREN", "FERRARI"],
    "car_numbers": [4, 16],
    "lap": 23,
    "sector": 2,
    "location": "Turns 9-10"
  },
  "severity": "MEDIUM"
}
```

### RaceState example

```json
{
  "schema_version": "1.0.0",
  "session_id": "australia_gp_replay_2026_qf",
  "tick_ts_utc": "2026-03-01T17:22:13Z",
  "lap": 23,
  "flag_status": "YELLOW",
  "weather": {
    "condition": "CLOUDY",
    "track_temp_c": 33.2,
    "air_temp_c": 24.1,
    "precipitation_pct": 10,
    "wind_kph": 15.4
  },
  "active_events": [
    {
      "event_id": "evt_20260301_00125",
      "event_type": "YELLOW_FLAG",
      "severity": "MEDIUM",
      "confidence": 0.92,
      "timestamp_s": 412.34
    }
  ]
}
```

### BetDecision example (explicit NO_BET path)

For `NO_BET`, this contract variant omits `market_id`.

```json
{
  "schema_version": "1.0.0",
  "decision_id": "dec_20260301_0090",
  "event_id": "evt_20260301_00125",
  "side": "NONE",
  "confidence": 0.88,
  "model_probability": 0.51,
  "market_implied_probability": 0.5,
  "edge_pct": 1,
  "kelly_fraction": 0,
  "size_usd": 0,
  "action": "NO_BET",
  "reason": "Edge is below minimum threshold after risk haircut; hold capital."
}
```
