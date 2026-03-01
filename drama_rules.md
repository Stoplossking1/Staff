# Drama Rules

## Scope
These rules define deterministic event-to-bet behavior for replay decisioning using:
- `RaceEvent` (`docs/contracts/race_event.schema.json`)
- `RaceState` (`docs/contracts/race_state.schema.json`)
- `BetDecision` (`docs/contracts/bet_decision.schema.json`)
- Event impact defaults in `docs/contracts/event_to_market_matrix.md`

All actions and sides must use contract enums:
- `action`: `PLACE_BET`, `MONITOR`, `NO_BET`
- `side`: `YES`, `NO`, `NONE`

## Deterministic Selection Order
1. Start from `race_state.active_events`.
2. Discard events with unsupported `event_type`.
3. Sort remaining events by:
   1. severity rank: `CRITICAL` > `HIGH` > `MEDIUM` > `LOW` > `INFO`
   2. confidence descending
   3. `timestamp_s` ascending
   4. `event_id` lexicographic ascending
4. Select the first event after sorting as the decision anchor.
5. Choose market using `bet_library.json` `market_priority`: first live market found in `candidate_markets`.

This guarantees identical replay inputs produce identical event/market selection.

## Action Ladder
1. Apply hard `NO_BET` checks.
2. If no hard block, evaluate `PLACE_BET` threshold first.
3. If `PLACE_BET` is not eligible, evaluate `MONITOR` threshold.
4. If none pass, return `NO_BET`.

This ordering is strict and deterministic: never return `MONITOR` if `PLACE_BET` eligibility is satisfied.

## Hard NO_BET Checks
Return `action=NO_BET`, `side=NONE`, `kelly_fraction=0`, `size_usd=0` when any is true:
- `active_events` is empty.
- `event.confidence` is below per-type minimum in `bet_library.json`.
- `decision.confidence < 0.65`.
- `abs(edge_pct) < 1.0`.
- No live candidate market is available.
- Quote age > 10 seconds.
- Liquidity < 1000 USD.
- `flag_status` is `RED` or `DOUBLE_YELLOW`.
- If `cooldown_state.last_neutralization` is `YELLOW_FLAG` or `VSC`, `cooldown_state.seconds_since_green_from_yellow_or_vsc` must be >= 20.
- If `cooldown_state.last_neutralization` is `SAFETY_CAR`, `cooldown_state.seconds_since_safety_car_restart` must be >= 30.
- Event policy marks `supports_place_bet=false` while evaluating the `PLACE_BET` branch.
- Event default policy is explicit `NO_BET` (`YELLOW_FLAG`, `SAFETY_CAR`, `TRACK_LIMITS`).

## Cooldown Inputs
Decisioning consumes cooldown metadata from `RaceState.cooldown_state`:
- `last_neutralization`: `NONE` | `YELLOW_FLAG` | `VSC` | `SAFETY_CAR`
- `seconds_since_green_from_yellow_or_vsc`: non-negative number
- `seconds_since_safety_car_restart`: non-negative number

## Side Mapping
- `NO_BET` -> `side=NONE`.
- `MONITOR`:
  - `edge_pct >= 1.0` -> `YES`
  - `edge_pct <= -1.0` -> `NO`
  - otherwise `NONE`
- `PLACE_BET`:
  - `edge_pct >= 3.0` and `decision.confidence >= 0.8` -> `YES`
  - `edge_pct <= -3.0` and `decision.confidence >= 0.8` -> `NO`
  - otherwise fallback to `MONITOR` or `NO_BET` by thresholds

## Event Coverage
`OVERTAKE`, `YELLOW_FLAG`, `SAFETY_CAR`, `VSC`, `PIT_STOP`, `CRASH`, `SPIN`, `TRACK_LIMITS`, `WEATHER_SHIFT`, `RETIREMENT`, `FASTEST_LAP`

Each event type is covered in `bet_library.json` with either candidate markets or an explicit `NO_BET` path.

## Required Examples

### Example 1: `CRASH` -> monitor then place eligible
Input:
- `event_type=CRASH`, `severity=HIGH`, `confidence=0.86`
- `flag_status=YELLOW`
- `edge_pct=2.2`, `decision.confidence=0.74`

Output:
- `action=MONITOR`
- `side=YES`
- Reason: above monitor edge threshold but below place threshold.

Escalation case:
- If incident confirms retirement and `edge_pct=4.1`, `decision.confidence=0.83`, market live -> `PLACE_BET`, `side=YES`.

### Example 2: `YELLOW_FLAG` -> explicit `NO_BET`
Input:
- `event_type=YELLOW_FLAG`, `confidence=0.91`
- `flag_status=YELLOW`

Output:
- `action=NO_BET`
- `side=NONE`
- Reason: explicit yellow-window hold rule.

### Example 3: `SAFETY_CAR` -> explicit `NO_BET`
Input:
- `event_type=SAFETY_CAR`, `confidence=0.97`
- `flag_status=SAFETY_CAR`

Output:
- `action=NO_BET`
- `side=NONE`
- Reason: suspension/discontinuous pricing risk during SC period.

### Example 4: `VSC` -> monitor by default
Input:
- `event_type=VSC`, `confidence=0.89`
- `flag_status=VSC`
- `edge_pct=1.6`, `decision.confidence=0.7`

Output:
- `action=MONITOR`
- `side=YES`
- Reason: monitor thresholds pass; place thresholds not met.

### Example 5: `OVERTAKE` -> persistence-gated action
Input:
- `event_type=OVERTAKE`, `confidence=0.79`
- pass occurred this lap but no one-lap persistence yet
- `edge_pct=3.5`, `decision.confidence=0.84`

Output:
- `action=MONITOR`
- `side=YES`
- Reason: overtake persistence gate not yet met.

Escalation case:
- After one full lap with sustained position and same edge/confidence -> `PLACE_BET`, `side=YES`.

### Example 6: `WEATHER_SHIFT` -> monitor until persistence
Input:
- `event_type=WEATHER_SHIFT`, `confidence=0.82`
- weather changed to `LIGHT_RAIN` for one tick only
- `edge_pct=2.7`, `decision.confidence=0.77`

Output:
- `action=MONITOR`
- `side=YES`
- Reason: weather persistence and place thresholds not yet met.

Escalation case:
- If weather shift persists for 2+ ticks and `edge_pct=3.3`, `decision.confidence=0.81` -> `PLACE_BET`, `side=YES`.
