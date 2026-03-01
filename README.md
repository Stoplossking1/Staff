# F1 Replay Event-to-Bet Contracts

This repository coordinates an F1 replay pipeline: replay video ingestion (`f1-stream`) -> Browser Use vision event detection -> race state aggregation -> paper betting decisioning.

## Architecture Summary
- Replay source: `f1-stream` with real replay asset (`lando.mp4`).
- Detection layer: emits `RaceEvent` contract payloads.
- State layer: emits `RaceState` snapshots with active events.
- Decision layer: emits `BetDecision` outputs with explicit `NO_BET` path.
- Orchestration layer: phase gating and PR checklist enforcement for multi-agent merges.

## Phase Order
1. Phase 0: A0 only (contracts + orchestration docs).
2. Phase 1: A1 + A2 + A3 in parallel (after Phase 0 merged).
3. Phase 2: A4 + A5 + A6 in parallel (after all Phase 1 merged).
4. Phase 3: A7 QA/demo (after all Phase 2 merged).

No phase advancement without previous phase merge + checklist pass.

## Branch Naming Convention
- Required prefix: `Stoplossking1/`
- Format: `Stoplossking1/<short-specific-name>`
- Example: `Stoplossking1/contracts-layer`

## Contract Links
- [RaceEvent schema](docs/contracts/race_event.schema.json)
- [RaceState schema](docs/contracts/race_state.schema.json)
- [BetDecision schema](docs/contracts/bet_decision.schema.json)
- [Event-to-market matrix](docs/contracts/event_to_market_matrix.md)

Contracts are versioned via top-level `schema_version`.

## Merge Gate Checklist
- Previous phase merged before starting next phase.
- PR includes: Inputs consumed.
- PR includes: Outputs produced.
- PR includes: Schema changes (none/version bump).
- PR includes: Local test command.
- PR includes: Evidence paths/logs.
- Contract validation passes for all produced/consumed payloads.

Detailed merge controls:
- [Merge plan](docs/orchestration/merge_plan.md)
- [PR checklist template](docs/orchestration/pr_checklist.md)
