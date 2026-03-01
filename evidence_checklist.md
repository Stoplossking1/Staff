# Evidence Checklist

## Status
- [x] Core replay-to-decision flow tests added
- [x] Weak-signal `NO_BET` behavior verified
- [x] Threshold-met `PLACE_BET` behavior verified
- [x] Trace correlation evidence generated
- [x] Strict JSON Schema validation executed and passing

## Test Evidence
- Integration test file: `tests/test_replay_e2e_flow.py`
- Strict test command: `.context/qa-venv/bin/python -m unittest tests/test_replay_e2e_flow.py`
- Full suite command: `.context/qa-venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- Latest local results:
  - `Ran 3 tests ... OK`
  - `Ran 24 tests ... OK`

## Sample Output Evidence
- Weak-signal decision sample:
  - `.context/evidence/demo/weak_signal_no_bet_decision.json`
  - Expected: `"action": "NO_BET"`, `"side": "NONE"`, `"size_usd": 0`
- Threshold-met decision sample:
  - `.context/evidence/demo/threshold_met_place_bet_decision.json`
  - Expected: `"action": "PLACE_BET"`, `"side": "YES"`, `"size_usd" > 0`

## Trace References
- Weak signal trace:
  - `.context/evidence/demo/weak_signal_no_bet_trace.jsonl`
  - `detection_summary.event_count = 0`
  - `decision_output.action = NO_BET`
- Threshold-met trace:
  - `.context/evidence/demo/threshold_met_place_bet_trace.jsonl`
  - `detection_event.event_id = evt_120000_RETIREMENT_77`
  - `decision_output.action = PLACE_BET`
  - `decision_output.correlation.event_ids` contains emitted `event_id`

## Manifest
- `.context/evidence/demo/demo_manifest.json`
- Captures scenario outcomes, artifact paths, and strict contract-validation status.

## Contract Validation Result
- `.context/evidence/demo/demo_manifest.json` confirms:
  - `"jsonschema_available": true`
  - `"contract_validation": "passed"` for `weak_signal_no_bet`
  - `"contract_validation": "passed"` for `threshold_met_place_bet`
