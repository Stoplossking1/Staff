# Merge Plan

## Objective
Coordinate A0-A7 delivery with low-conflict sequencing and explicit merge gates.

## Phase Order (Enforced)
1. **Phase 0 - Contracts and orchestration (A0 only)**
- Scope: schemas, matrix, merge plan, PR checklist, root README alignment.
- Exit gate: all contract docs merged to `main`.
2. **Phase 1 - Core parallel build (A1 + A2 + A3)**
- Allowed only after Phase 0 is merged.
- Each PR must include the checklist from `docs/orchestration/pr_checklist.md`.
3. **Phase 2 - Integration parallel build (A4 + A5 + A6)**
- Allowed only after all Phase 1 PRs are merged and validated.
- Any schema edits require version bump note in PR checklist.
4. **Phase 3 - QA/demo (A7)**
- Allowed only after all Phase 2 PRs are merged and checklist-complete.
- Deliverables: demo run notes + final verification evidence.

## Advancement Rule
No phase advancement without previous phase merge + checklist pass.

## Integration Gates
- Gate 1: Schema compatibility
- Validate `RaceEvent`, `RaceState`, `BetDecision` payloads against current schemas.
- Reject PR if required fields/enums regress.

- Gate 2: Contract linkage
- Producer PRs must show outputs produced and where written.
- Consumer PRs must show inputs consumed and fallback behavior.

- Gate 3: Evidence-backed validation
- Every PR must include a local test command and evidence paths/logs.
- If a test is unavailable, PR must explicitly state why and include manual verification steps.

## Merge Procedure
1. Rebase branch on latest `main`.
2. Run local tests listed in PR checklist.
3. Confirm checklist is complete and accurate.
4. Merge only if all gates pass.
