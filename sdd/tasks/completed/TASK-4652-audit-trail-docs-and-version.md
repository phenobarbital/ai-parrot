# TASK-4652: Audit-trail documentation + `parrot-formdesigner` version bump

**Feature**: FEAT-732 — FormDesigner validation audit trail
**Spec**: `sdd/specs/formdesigner-validation-audit-trail.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4644, TASK-4646, TASK-4649, TASK-4650, TASK-4651
**Assigned-to**: unassigned

---

## Context

An audit trail nobody can read is not an audit trail. A finance team needs to know what
`context["validation"]` contains, what every `CheckId` means, why there are three version
identifiers, how truncation is marked, and how to obtain the `read_form_audit` permission.
This task writes that page, adds the new `PlausibilityReport` fields to the FEAT-728 doc
(as audit-only, absent from the wire), adds a test that keeps the doc and the `CheckId` enum
from drifting apart, and bumps the package version. Implements spec §3 Module 7 and AC21/AC23.

It runs last because it documents the finished surface of every other task.

---

## Scope

- Create `docs/formdesigner-validation-audit-trail.md`.
- Add §4.5 to `docs/formdesigner-llm-validation-enforcement.md` and a §10 link.
- Create `tests/unit/test_audit_trail_docs.py`: the page exists and names every `CheckId`
  value, every `SkipReason` value, and `read_form_audit`.
- Bump `__version__` to the **next minor of whatever `dev` holds when this task runs**.

**NOT in scope**:
- Any source change other than `version.py`.
- Updating `test_version_and_docs.py`. Its `test_version_bumped` compares `__version__`
  with the *installed* distribution metadata, so it goes red in a worktree after any bump
  until the shared venv is re-installed from the main checkout (known issue, ledger
  `b48f3748e90e`). **Never run `uv sync` inside the worktree to "fix" it** — that repoints
  the shared venv at the worktree (`.claude/rules/worktree-management.md` §4).

### Why "next minor at run time", not the spec's `1.3.0`
FEAT-730 (TASK-4637) and FEAT-731 (TASK-4643) also bump this file. Hardcoding `1.3.0`
would collide with whichever lands first. Same convention as TASK-4643.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/formdesigner-validation-audit-trail.md` | CREATE | The audit-trail reference page |
| `docs/formdesigner-llm-validation-enforcement.md` | MODIFY | §4.5 audit-only report fields; §10 link |
| `packages/parrot-formdesigner/tests/unit/test_audit_trail_docs.py` | CREATE | Doc ↔ enum drift guard |
| `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` | MODIFY | Version bump |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.audit_trail import CheckId, SkipReason   # TASK-4644
from parrot_formdesigner.api.handlers import READ_FORM_AUDIT           # TASK-4651
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/version.py
__version__ = "1.2.4"      # line 5 at spec time — FEAT-730/731 may have bumped it first; bump the THEN-current minor
# pyproject reads it dynamically: [tool.setuptools.dynamic] version = {attr = "parrot_formdesigner.version.__version__"}

# docs/formdesigner-llm-validation-enforcement.md
## 4. Wire shapes                       # line 71
## 5. Configuring a form                # line 168 ← insert §4.5 above this heading
## 10. Related documentation            # line 356 ← append a link in this section

# tests locate the repo docs dir like tests/unit/test_version_and_docs.py:10 does:
#   Path(__file__).parents[4] / "docs"
```

### Facts the page must state (all verified in the spec and the tasks — do not invent others)
- Storage: `FormSubmission.context["validation"]` (JSONB, no new column, no migration).
- Detail levels: `summary` (default), `full` (opt-in), `off`. Configured by
  `FormSchema.audit_trail = {"detail": ..., "max_bytes": ...}`.
- Cap defaults: 64 KiB `summary` / 256 KiB `full`; explicit `max_bytes` (1024 – 1 048 576)
  overrides either way. Measured coverage: `summary` 239–352 fields, `full` 235–440 fields.
- Truncation markers: `truncated`, `omitted_fields`, `omitted_checks`; failures are dropped last.
- Three identifiers and why: `form_version` (author string), `schema_fingerprint`
  (`sha256:` over the validation subset), `ruleset_version` (package version).
- Recording rules: undeclared checks are never recorded; the TASK-4649 rules table.
- Form-level early returns carry `fields: []` (TASK-4648 deviation) — say why.
- LLM identity: `resolved_model` / `provider` / `usage` are persisted in
  `context["llm_validation"]`, **never** sent to form clients; `model` still means "requested".
  The no-call `ok` (no eligible fields) has `resolved_model: null`.
- Read path: `GET {base}/{tenant}/forms/{form_uid}/data/{submission_id}/audit`; requires
  `read_form_audit` at `client` scope or wider; granted per user with
  `POST {base}/org/users/{user_id}/assign` (body `{"codename": "read_form_audit", "scope": "client", "program_id": <id>}`);
  403/404/501/503 semantics; never seeded, so it 403s until granted.
- Not covered: validate-only channels (Telegram, `ui/` handlers, MS Teams presets, audio
  client-submit) persist no trace; FEAT-457 sink-persisted forms answer 501 on the read
  path; YAML-defined forms do not yet load `audit_trail`; ARRAY `item_template` rules are
  not validated on submit, so they never appear in a trace.

### Does NOT Exist
- ~~a migration or DDL for the trace~~ — there is none; do not document one.
- ~~`audit_trail.enabled`~~ — the switch is `detail: "off"`.
- ~~a default `read_form_audit` policy~~ — never seeded.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/formdesigner-validation-audit-trail.md", "action": "CREATE"},
    {"path": "docs/formdesigner-llm-validation-enforcement.md", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_audit_trail_docs.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/version.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the page from the "Facts the page must state" list — *why*: every claim in it is
   verified; anything else would be invention.
2. Add §4.5 and the §10 link to the FEAT-728 doc — *why*: that doc defines the wire shapes,
   and readers of it must learn the new fields are audit-only.
3. Write the drift-guard test — *why*: a `CheckId` added later without a doc entry fails CI.
4. Bump the version last — *why*: it is the exclusive step.

### `docs/formdesigner-validation-audit-trail.md` (CREATE — skeleton)
```markdown
# FormDesigner — validation audit trail

> **Feature**: FEAT-732
> **Package**: `parrot-formdesigner` >= <the version this task bumps to>
> **Builds on**: FEAT-728 ([`formdesigner-llm-validation-enforcement.md`](formdesigner-llm-validation-enforcement.md))

## 1. What gets recorded, and where
## 2. Detail levels and the size cap
## 3. Reading a trace — the three identifiers
## 4. Check reference          <!-- one row per CheckId value: id | what it checks | bound format -->
## 5. Skip reasons            <!-- one row per SkipReason value -->
## 6. LLM identity in the record
## 7. Reading the audit trail — endpoint and permission
## 8. What is NOT covered
```
FILL IN every section from the facts list. The §4 and §5 tables must contain each enum
value **verbatim** (e.g. `constraint.max_length`) — the drift test greps for them.

### `docs/formdesigner-llm-validation-enforcement.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## 5. Configuring a form' docs/formdesigner-llm-validation-enforcement.md)
     BEFORE — insert above `## 5. Configuring a form` (verified: line 168) -->
### 4.5 Audit-only report fields (FEAT-732)

`PlausibilityReport` also carries `resolved_model`, `provider` and `usage` — what actually
answered, and at what token cost. They are **persisted** in `context["llm_validation"]` and
are **never** part of any response above: every client-facing dump goes through
`wire_report()`, so the shapes in §4.1–§4.4 are unchanged. `model` keeps its meaning: the
model the configuration *requested*, `null` when the client default was used.
See [`formdesigner-validation-audit-trail.md`](formdesigner-validation-audit-trail.md).
```
and append under `## 10. Related documentation` (line 356) a bullet linking
`formdesigner-validation-audit-trail.md`.

### `packages/parrot-formdesigner/tests/unit/test_audit_trail_docs.py` (CREATE)
```python
"""FEAT-732 — the audit-trail page documents every check id and skip reason."""

from pathlib import Path

from parrot_formdesigner.api.handlers import READ_FORM_AUDIT
from parrot_formdesigner.core.audit_trail import CheckId, SkipReason

PAGE = Path(__file__).parents[4] / "docs" / "formdesigner-validation-audit-trail.md"


def test_page_exists() -> None:
    assert PAGE.is_file()


def test_every_check_id_documented() -> None:
    text = PAGE.read_text()
    missing = [c.value for c in CheckId if f"`{c.value}`" not in text]
    assert not missing, f"undocumented CheckId values: {missing}"


def test_every_skip_reason_documented() -> None:
    # FILL IN: same shape as above, over SkipReason


def test_permission_codename_documented() -> None:
    assert f"`{READ_FORM_AUDIT}`" in PAGE.read_text()
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '__version__ = ' version.py)
# REPLACE the `__version__ = "<current>"` line with the next MINOR of the current value
#   (e.g. "1.2.4" → "1.3.0"; "1.3.0" → "1.4.0"). Read the current value first — do not assume 1.2.4.
```

### FILL IN checklist
- [ ] Every page section — only from the facts list.
- [ ] `test_every_skip_reason_documented`.
- [ ] Version value — next minor of what `dev` holds now.

---

## Acceptance Criteria

- [ ] `docs/formdesigner-validation-audit-trail.md` exists and its §4/§5 tables list every
      `CheckId` and `SkipReason` value verbatim (spec AC21).
- [ ] The page documents the grant path and that the endpoint 403s until granted (spec AC23).
- [ ] The FEAT-728 doc has §4.5 and a §10 link; §4.1–§4.4 are unchanged.
- [ ] `__version__` is the next minor of the value `dev` held when the task ran.
- [ ] The drift-guard tests pass.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_audit_trail_docs.py -q`

---

## Test Specification

See the full test module in the blueprint above — it is short enough to be given whole.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug formdesigner-validation-audit-trail --feature-id FEAT-732`
2. **Read the spec** — §3 Module 7, §5 AC21/AC23, and the Completion Notes of TASK-4644…4651
   (they record the deviations the page must describe).
3. **Check dependencies** — TASK-4644, 4646, 4649, 4650, 4651 must all be `done`.
4. **Verify the Codebase Contract** — re-run every `grep -c`; read the current `__version__`.
5. **Update status** → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
   Do NOT add `test_version_and_docs.py` and do NOT `uv sync` (see NOT in scope).
8. **Commit the code** — stage only the four listed files.
9. **Close** — `scripts/sdd/close_task.sh TASK-4652 formdesigner-validation-audit-trail verified`.
10. **Completion Note** — record the version chosen and what `dev` held when you chose it.

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat gemini (gemini-3.5-flash), attempt 1 (uid f7adef0f98ec421cbae3b7744b00c767), duration 173s
**Date**: 2026-10-23
**Notes**: Audit-trail docs page, cross-link in the LLM-validation doc, version bump to 1.3.0, docs test. Orchestrator corrected docs that misdescribed truncation and the audit endpoint responses (fix bc3f5f8b7); feedback coder-feedback:a705c9a1196705999e38a339. Merge-tier validation green. Closed with close_task.sh (engine exposes no durable review-evidence ref for finalize_task).

**Deviations from spec**: none
