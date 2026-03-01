import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const upsert = mutation({
  args: {
    name: v.string(),
    version: v.string(),
    config: v.any(),
    updated_at_utc: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("bet_library")
      .withIndex("by_name_version", (q) =>
        q.eq("name", args.name).eq("version", args.version)
      )
      .first();
    if (existing) {
      await ctx.db.patch(existing._id, {
        config: args.config,
        updated_at_utc: args.updated_at_utc,
      });
      return existing._id;
    }
    return await ctx.db.insert("bet_library", args);
  },
});

export const getCurrent = query({
  args: { name: v.optional(v.string()) },
  handler: async (ctx, args) => {
    const name = args.name ?? "event_to_bet_policy";
    return await ctx.db
      .query("bet_library")
      .withIndex("by_name_updated", (q) => q.eq("name", name))
      .order("desc")
      .first();
  },
});
