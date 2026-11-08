# TASK-5360: Documentation — `wiki/sdd-tooling/sdd/agy-compatibility.md`

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5349, TASK-5350, TASK-5354, TASK-5356, TASK-5357, TASK-5359
**Assigned-to**: unassigned

---

## Context

Spec §10 (`docs.policy: required`). One page: the architecture and operator guide for running SDD workflows and
sub-agents in Google Antigravity CLI (`agy`) — `.agents/hooks.json` and the single `parrot-sdd-permissions` hook,
the unattended mode, `docs/sdd/AGY.md`, the official install, and why the community snap is unsupported. It runs
last because it documents what every other task built.

---

## Scope

- Create `wiki/sdd-tooling/sdd/agy-compatibility.md` from `sdd/templates/techwiki-page.md`.
- Create `packages/ai-parrot/tests/sdd/test_agy_compat_docs.py`: the spec's docs decision is `ok`, and the page
  names the facts operators need.

**NOT in scope**: `docs/sdd/AGY.md` (TASK-5358); code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/sdd-tooling/sdd/agy-compatibility.md` | CREATE | architecture + operator guide |
| `packages/ai-parrot/tests/sdd/test_agy_compat_docs.py` | CREATE | techwiki decision + content checks |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09).

### Verified Imports
```python
from parrot.sdd.techwiki.check import evaluate_docs, resolve_docs_policy   # techwiki/check.py:31, 103
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/techwiki/check.py
def resolve_docs_policy(spec_path: Path) -> tuple[str, list[str], list[str]]:              # line 31 — (policy, pages, api_modules)
def evaluate_docs(policy: str, pages: list[str], api_modules: list[str], root: Path) -> DocsDecision:  # line 103
class DocsDecision:  # line 20 — .policy, .status ("ok"|"warning"|"skipped"|"invalid"), .reason_codes, .missing
# CLI equivalent: parrot sdd techwiki check --spec sdd/specs/sdd-agy-compatibility.spec.md --root .  (never blocks; exit 2 only when invalid)
# Template: sdd/templates/techwiki-page.md — front matter (title, summary) + Purpose / Public API / Configuration &
#   Parameters / Usage Examples / Gotchas / Related; API links use `ref:<dotted.path>`
# Related existing page: wiki/sdd-tooling/sdd/ANTIGRAVITY.md
```

### Does NOT Exist
- ~~A snap backend, vendored `.agents/hooks/*.py`, a second SDD hook~~ — do not document them as features.
- ~~A blocking `techwiki check`~~ — it is advisory; the test asserts `status == "ok"` itself.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/sdd-tooling/sdd/agy-compatibility.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_agy_compat_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged code of TASK-5347…5359 (names below) — *why*: the page must match what shipped.
2. Write the page from the template — *why*: spec §10.
3. Write the test; run `parrot sdd techwiki check --spec sdd/specs/sdd-agy-compatibility.spec.md --root .`.

### `wiki/sdd-tooling/sdd/agy-compatibility.md` (CREATE)
```markdown
---
title: SDD on Google Antigravity (agy)
summary: How the SDD workflow, its hook guard and its sub-agents run under the agy CLI, attended and unattended.
---

# SDD on Google Antigravity (agy)

## Purpose
<!-- FILL IN: what works under agy and how (skills + agents + one hook); link docs/sdd/AGY.md. -->

## Public API
- [`agy_verdict`](ref:parrot.sdd.scripts.worktree_environment.agy_verdict) — worktree-environment guard and file containment for one AGY event
- [`evaluate`](ref:parrot.sdd.scripts.agy_permissions.evaluate) — the `parrot-sdd-permissions` hook decision (deny > force_ask > ask, unattended mapping)
- [`launch_agy_worker`](ref:parrot.flows.dev_loop.feature_launcher.launch_agy_worker) — the unattended worker launch
- [`launch_session`](ref:parrot.flows.dev_loop.feature_launcher.launch_session) — interactive brief/fix sessions
- [`GoogleCodingDispatchProfile`](ref:parrot.flows.dev_loop.models.google_coding.GoogleCodingDispatchProfile) — dispatcher seat profile
<!-- FILL IN: add the installer and launch_cli entries for the remaining api_modules of spec §10. -->

## Configuration & Parameters
<!-- FILL IN: `parrot sdd install --host google` (hook matcher run_command|write_file|edit_file, allow-rules,
     --no-agy-permissions); `parrot sdd launch worker|brief|fix --host google` and PARROT_SDD_HOST;
     PARROT_SDD_AGY_UNATTENDED / PARROT_SDD_SANDBOX_BACKEND=bubblewrap; GoogleCodingDispatchProfile mode/effort. -->

## Usage Examples
<!-- FILL IN: install, launch worker (unattended), launch brief/fix (interactive), with expected refusals. -->

## Gotchas
<!-- FILL IN: hook `allow` approves nothing; `force_ask` runs under --dangerously-skip-permissions (hence the
     unattended mapping); only the launcher's worker is a supported unattended mode; --mode auto is account-gated;
     the snap is refused (official install command); fresh shell per run_command; self-updating agy — re-run the
     probes after hook/permission changes. -->

## Related
- [Antigravity notes](ANTIGRAVITY.md) — earlier agy integration notes
<!-- FILL IN: link docs/sdd/AGY.md and the agy-permission-hook brief. -->
```

### `packages/ai-parrot/tests/sdd/test_agy_compat_docs.py` (CREATE)
```python
"""FEAT-847 §10 — the declared documentation page exists and covers the operator facts."""

from __future__ import annotations

from pathlib import Path

from parrot.sdd.techwiki.check import evaluate_docs, resolve_docs_policy

REPO_ROOT = Path(__file__).resolve().parents[4]
SPEC = REPO_ROOT / "sdd/specs/sdd-agy-compatibility.spec.md"
PAGE = REPO_ROOT / "wiki/sdd-tooling/sdd/agy-compatibility.md"


def test_spec_documentation_decision_is_ok() -> None:
    policy, pages, api_modules = resolve_docs_policy(SPEC)
    decision = evaluate_docs(policy, pages, api_modules, REPO_ROOT)
    assert decision.status == "ok", (decision.reason_codes, decision.missing)


# FILL IN: test_page_names_operator_facts — PAGE text contains "--host google", "PARROT_SDD_AGY_UNATTENDED",
#   "run_command|write_file|edit_file", "install.sh", "snap", "docs/sdd/AGY.md".
```

### FILL IN checklist
- [ ] every page section; bounded by spec §10 and the shipped code
- [ ] `test_page_names_operator_facts`

---

## Acceptance Criteria

- [ ] `wiki/sdd-tooling/sdd/agy-compatibility.md` exists, follows the template and matches the shipped behaviour.
- [ ] `parrot sdd techwiki check --spec sdd/specs/sdd-agy-compatibility.spec.md --root .` reports `ok`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_agy_compat_docs.py -q`

---

## Test Specification

See `test_agy_compat_docs.py` in the Implementation Blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-agy-compatibility --feature-id FEAT-847`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/sdd-agy-compatibility.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` in a worktree)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5360 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
