# Replay Flow Demo Runbook

## Scope
Validate replay-to-decision behavior for:
- Contract-compliant payload generation
- `NO_BET` on weak/uncertain signals
- `PLACE_BET` when thresholds and gates are satisfied

## Preconditions
- Run from repo root.
- Python 3.11+ available.
- No external APIs required for this QA replay demo.
- Prepare QA venv once:

```bash
python3 -m venv .context/qa-venv
.context/qa-venv/bin/python -m pip install --upgrade pip
.context/qa-venv/bin/python -m pip install jsonschema referencing
```

## Demo Commands
1. Run core QA integration tests:

```bash
.context/qa-venv/bin/python -m unittest tests/test_replay_e2e_flow.py
```

Expected result:
- 3 tests run.
- No skips.

2. Run full test suite:

```bash
.context/qa-venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Expected result:
- All tests pass.
- Same optional strict-contract skip behavior.

3. Generate demo evidence artifacts:

```bash
.context/qa-venv/bin/python tests/generate_demo_evidence.py --output-dir .context/evidence/demo --strict-contracts
```

Expected artifacts:
- `.context/evidence/demo/demo_manifest.json`
- `.context/evidence/demo/weak_signal_no_bet_race_state.json`
- `.context/evidence/demo/weak_signal_no_bet_race_events.json`
- `.context/evidence/demo/weak_signal_no_bet_decision.json`
- `.context/evidence/demo/weak_signal_no_bet_trace.jsonl`
- `.context/evidence/demo/threshold_met_place_bet_race_state.json`
- `.context/evidence/demo/threshold_met_place_bet_race_events.json`
- `.context/evidence/demo/threshold_met_place_bet_decision.json`
- `.context/evidence/demo/threshold_met_place_bet_trace.jsonl`

## Demo Assertions
- Weak signal scenario yields:
  - `event_count = 0`
  - decision `action = NO_BET`
  - no correlated `event_ids` in decision trace
- Threshold-met scenario yields:
  - `event_count = 1` with `RETIREMENT` event
  - decision `action = PLACE_BET`
  - non-zero `size_usd`
  - decision trace correlated to emitted `event_id`

## Strict Contract Validation Confirmation
- `demo_manifest.json` must show:
  - `"jsonschema_available": true`
  - `"contract_validation": "passed"` for each scenario.
