import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const insert = mutation({
  args: {
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
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("race_events", args);
  },
});

export const listBySession = query({
  args: { session_id: v.string(), limit: v.optional(v.float64()) },
  handler: async (ctx, args) => {
    const n = args.limit ?? 200;
    return await ctx.db
      .query("race_events")
      .withIndex("by_session_and_time", (q) =>
        q.eq("session_id", args.session_id)
      )
      .order("desc")
      .take(n);
  },
});
