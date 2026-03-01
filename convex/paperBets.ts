import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const insert = mutation({
  args: {
    session_id: v.string(),
    schema_version: v.optional(v.string()),
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
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("paper_bets", args);
  },
});

export const listBySession = query({
  args: { session_id: v.string(), limit: v.optional(v.float64()) },
  handler: async (ctx, args) => {
    const n = args.limit ?? 200;
    return await ctx.db
      .query("paper_bets")
      .withIndex("by_session_and_time", (q) =>
        q.eq("session_id", args.session_id)
      )
      .order("desc")
      .take(n);
  },
});

export const listRecent = query({
  args: { limit: v.optional(v.float64()) },
  handler: async (ctx, args) => {
    const n = args.limit ?? 50;
    return await ctx.db
      .query("paper_bets")
      .order("desc")
      .take(n);
  },
});
