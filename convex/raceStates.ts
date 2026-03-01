import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const insert = mutation({
  args: {
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
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("race_states", args);
  },
});

export const latestBySession = query({
  args: { session_id: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("race_states")
      .withIndex("by_session_and_tick", (q) =>
        q.eq("session_id", args.session_id)
      )
      .order("desc")
      .first();
  },
});
