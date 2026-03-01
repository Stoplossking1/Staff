#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const root = process.cwd();

function readJson(relPath) {
  const absPath = path.join(root, relPath);
  return JSON.parse(fs.readFileSync(absPath, 'utf8'));
}

function readText(relPath) {
  const absPath = path.join(root, relPath);
  return fs.readFileSync(absPath, 'utf8');
}

function setEquals(a, b) {
  if (a.size !== b.size) return false;
  for (const item of a) {
    if (!b.has(item)) return false;
  }
  return true;
}

const errors = [];

function expect(condition, message) {
  if (!condition) {
    errors.push(message);
  }
}

const betLibrary = readJson('bet_library.json');
const raceStateSchema = readJson('docs/contracts/race_state.schema.json');
const commonSchema = readJson('docs/contracts/_common.schema.json');
const dramaRules = readText('drama_rules.md');
const visionPrompt = readText('vision_system_prompt.md');

const expectedOrder = ['HARD_NO_BET', 'PLACE_BET', 'MONITOR', 'NO_BET_FALLBACK'];
expect(
  JSON.stringify(betLibrary.decision_guardrails?.evaluation_order) === JSON.stringify(expectedOrder),
  `decision_guardrails.evaluation_order must equal ${JSON.stringify(expectedOrder)}`
);

expect(
  betLibrary.decision_guardrails?.decision_confidence?.monitor_min <
    betLibrary.decision_guardrails?.decision_confidence?.place_bet_min,
  'decision confidence thresholds must satisfy monitor_min < place_bet_min'
);

expect(
  betLibrary.decision_guardrails?.edge_pct?.monitor_min_abs <
    betLibrary.decision_guardrails?.edge_pct?.place_bet_min_abs,
  'edge thresholds must satisfy monitor_min_abs < place_bet_min_abs'
);

const supportedEventTypes = new Set(betLibrary.supported_event_types || []);
const ruleEventTypes = new Set((betLibrary.event_type_rules || []).map((rule) => rule.event_type));
const contractEventTypes = new Set(commonSchema.$defs?.event_type?.enum || []);

expect(setEquals(supportedEventTypes, ruleEventTypes), 'supported_event_types must match event_type_rules.event_type set exactly');
expect(setEquals(supportedEventTypes, contractEventTypes), 'supported_event_types must match contracts/_common.schema.json event_type enum');

const hardNoBetConditions = betLibrary.hard_no_bet_conditions || [];
expect(
  hardNoBetConditions.some((line) => line.trim() === 'race_state.cooldown_state is absent.'),
  'hard_no_bet_conditions must fail closed when cooldown_state is absent'
);
expect(
  hardNoBetConditions.some((line) => line.includes('seconds_since_green_from_yellow_or_vsc')),
  'hard_no_bet_conditions must enforce post-green cooldown from yellow/VSC'
);
expect(
  hardNoBetConditions.some((line) => line.includes('seconds_since_safety_car_restart')),
  'hard_no_bet_conditions must enforce post-safety-car restart cooldown'
);
expect(
  hardNoBetConditions.some((line) => line.includes('When evaluating PLACE_BET eligibility')),
  'hard_no_bet_conditions must define supports_place_bet guard in evaluation-branch terms'
);

const cooldownState = raceStateSchema.properties?.cooldown_state;
expect(Boolean(cooldownState), 'RaceState schema must define cooldown_state');
expect(
  Array.isArray(cooldownState?.required) && cooldownState.required.includes('last_neutralization'),
  'cooldown_state must require last_neutralization'
);
expect(
  Array.isArray(cooldownState?.required) && cooldownState.required.includes('seconds_since_green_from_yellow_or_vsc'),
  'cooldown_state must require seconds_since_green_from_yellow_or_vsc'
);
expect(
  Array.isArray(cooldownState?.required) && cooldownState.required.includes('seconds_since_safety_car_restart'),
  'cooldown_state must require seconds_since_safety_car_restart'
);
expect(
  Array.isArray(cooldownState?.properties?.seconds_since_green_from_yellow_or_vsc?.type) &&
    cooldownState.properties.seconds_since_green_from_yellow_or_vsc.type.includes('null'),
  'seconds_since_green_from_yellow_or_vsc must allow null'
);
expect(
  Array.isArray(cooldownState?.properties?.seconds_since_safety_car_restart?.type) &&
    cooldownState.properties.seconds_since_safety_car_restart.type.includes('null'),
  'seconds_since_safety_car_restart must allow null'
);

expect(
  dramaRules.includes('evaluate `PLACE_BET` threshold first') && dramaRules.includes('never return `MONITOR` if `PLACE_BET` eligibility is satisfied'),
  'drama_rules.md must define strict PLACE_BET-before-MONITOR precedence'
);
expect(
  dramaRules.includes('Cooldown Inputs') && dramaRules.includes('cooldown_state.seconds_since_green_from_yellow_or_vsc'),
  'drama_rules.md must document cooldown decision inputs'
);
expect(
  dramaRules.includes('If `cooldown_state` is absent, fail closed:'),
  'drama_rules.md must define fail-closed behavior when cooldown_state is absent'
);
expect(
  betLibrary.fallback_behavior?.missing_cooldown_state?.action === 'NO_BET' &&
    betLibrary.fallback_behavior?.missing_cooldown_state?.side === 'NONE',
  'fallback_behavior.missing_cooldown_state must explicitly define NO_BET/NONE'
);

expect(
  visionPrompt.includes('primary_entity_or_NA must be derived as') &&
    visionPrompt.includes('smallest car number') &&
    visionPrompt.includes('lexicographically smallest driver code'),
  'vision_system_prompt.md must define deterministic primary entity derivation'
);
expect(
  visionPrompt.includes('If confidence ties, keep lower timestamp_s; if still tied, keep lexicographically smaller event_id.'),
  'vision_system_prompt.md must define dedupe tie-breakers'
);

if (errors.length > 0) {
  console.error('Policy consistency check FAILED:');
  for (const [index, error] of errors.entries()) {
    console.error(`${index + 1}. ${error}`);
  }
  process.exit(1);
}

console.log('Policy consistency check passed.');
