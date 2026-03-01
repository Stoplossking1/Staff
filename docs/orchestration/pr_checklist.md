# PR Checklist

Copy this into every PR description.

## Required Sections
- [ ] Inputs consumed
- [ ] Outputs produced
- [ ] Schema changes (none/version bump)
- [ ] Local test command
- [ ] Evidence paths/logs

## Template

### Inputs consumed
- Contract(s):
- Upstream service/module:
- Assumptions:

### Outputs produced
- Produced artifact(s):
- Output location(s):
- Downstream consumers:

### Schema changes (none/version bump)
- Status: `none` or `version bump`
- If bumped, describe backward-compatibility handling:

### Local test command
- Command(s):
- Result summary:
- Recommended minimum: `node scripts/validate_policy_consistency.js`

### Evidence paths/logs
- File path(s):
- Log snippet summary:

## Gate Reminder
No phase advancement without previous phase merge + checklist pass.
