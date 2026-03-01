import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  paper_bets: defineTable({
    session_id: v.string(),
    logged_at_utc: v.string(),
    decision_id: v.string(),
    event_id: v.string(),
    market_id: v.optional(v.string()),
    action: v.string(),
    fire_state: v.string(),
    side: v.string(),
    confidence: v.float64(),
    model_probability: v.float64(),
    market_implied_probability: v.float64(),
    edge_pct: v.float64(),
    kelly_fraction: v.float64(),
    size_usd: v.float64(),
    bankroll_usd: v.float64(),
    reason: v.string(),
    schema_version: v.string(),
  })
    .index("by_decision_id", ["decision_id"])
    .index("by_session_and_time", ["session_id", "logged_at_utc"]),

  race_events: defineTable({
    session_id: v.string(),
    schema_version: v.string(),
    event_id: v.string(),
    timestamp_s: v.float64(),
    event_type: v.string(),
    confidence: v.float64(),
    severity: v.string(),
    evidence: v.object({
      source: v.string(),
      start_s: v.float64(),
      end_s: v.float64(),
      summary: v.string(),
      frame_refs: v.optional(v.array(v.string())),
    }),
    entities: v.object({
      drivers: v.optional(v.array(v.string())),
      teams: v.optional(v.array(v.string())),
      car_numbers: v.optional(v.array(v.float64())),
      lap: v.optional(v.float64()),
      sector: v.optional(v.float64()),
      location: v.optional(v.string()),
    }),
  })
    .index("by_event_id", ["event_id"])
    .index("by_session_and_time", ["session_id", "timestamp_s"]),

  race_states: defineTable({
    session_id: v.string(),
    schema_version: v.string(),
    tick_ts_utc: v.string(),
    lap: v.float64(),
    flag_status: v.string(),
    weather: v.object({
      condition: v.string(),
      track_temp_c: v.float64(),
      air_temp_c: v.float64(),
      precipitation_pct: v.float64(),
      wind_kph: v.float64(),
    }),
    active_events: v.array(
      v.object({
        event_id: v.string(),
        event_type: v.string(),
        severity: v.string(),
        confidence: v.float64(),
        timestamp_s: v.float64(),
      })
    ),
    cooldown_state: v.optional(
      v.object({
        last_neutralization: v.string(),
        seconds_since_green_from_yellow_or_vsc: v.optional(v.float64()),
        seconds_since_safety_car_restart: v.optional(v.float64()),
      })
    ),
  })
    .index("by_session_and_tick", ["session_id", "tick_ts_utc"]),

  sessions: defineTable({
    session_id: v.string(),
    status: v.string(),
    config: v.any(),
    started_at_utc: v.optional(v.string()),
    updated_at_utc: v.string(),
  })
    .index("by_session_id", ["session_id"])
    .index("by_status", ["status"]),

  bet_library: defineTable({
    name: v.string(),
    version: v.string(),
    config: v.any(),
    updated_at_utc: v.string(),
  })
    .index("by_name_version", ["name", "version"])
    .index("by_name_updated", ["name", "updated_at_utc"]),
});
