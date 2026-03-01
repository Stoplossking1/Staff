import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const upsert = mutation({
  args: {
    session_id: v.string(),
    status: v.string(),
    config: v.any(),
    updated_at_utc: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("sessions")
      .withIndex("by_session_id", (q) => q.eq("session_id", args.session_id))
      .first();
    if (existing) {
      await ctx.db.patch(existing._id, {
        status: args.status,
        config: args.config,
        updated_at_utc: args.updated_at_utc,
      });
      return existing._id;
    }
    return await ctx.db.insert("sessions", {
      ...args,
      started_at_utc: args.updated_at_utc,
    });
  },
});

export const getActive = query({
  handler: async (ctx) => {
    return await ctx.db
      .query("sessions")
      .withIndex("by_status", (q) => q.eq("status", "active"))
      .collect();
  },
});

export const getBySessionId = query({
  args: { session_id: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("sessions")
      .withIndex("by_session_id", (q) => q.eq("session_id", args.session_id))
      .first();
  },
});
