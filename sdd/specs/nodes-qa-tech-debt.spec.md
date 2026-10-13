# QA Node / Test-Scope Tech Debt — FEAT-659

```yaml
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [dev-loop, qa, test-scope, tech-debt, ledger-fix]
```

## 1. Problem

Three tech-debt issues from the FEAT-604 adversarial code review:

1. **Unreachable cap-escalation plumbing** (issue:488a64ba2023, major) —
   `_record_green_escalations` in `qa.py` reads `plan.cap_hits`, but QANode
   calls `plan_tests(tier="feature")` and `select.py` only computes
   `cap_hits`/`cap_impacted` when `tier == "merge"`. The plumbing is dead code
   at the feature tier. Fix: remove the dead cap-escalation plumbing from qa.py
   and its unreachable test, add a comment in select.py confirming cap detection
   is merge-tier-only.

2. **Mutable dicts in frozen dataclass** (issue:f8d560ed8764, minor) —
   `ScopePlan` is `@dataclass(frozen=True)` but `cap_hits` and `cap_impacted`
   are plain `dict`. Other collection fields use immutable tuples. Fix: use
   `MappingProxyType` or `tuple[tuple[str, ...], ...]` for consistency.

3. **Nitpicks** (issue:4394a29b9202, low) — (a) `background.py` writes an
   empty file before `_append_log` (dead I/O); (b) qa.py criterion suffix says
   "core escalation" for non-core escalations; (c) vacuous hex assertion in
   `test_cap_escalation_ledger.py`.

## 2. Solution

### M1 — Remove dead cap-escalation plumbing from qa.py

Remove the `cap_hits`/`cap_impacted` reads from `_record_green_escalations`
and its associated `impact_files`/`impacted_hashes` parameters. Remove the
unreachable test `test_qa_records_cap_escalation_from_plan`.

### M2 — Freeze ScopePlan dict fields (datatypes.py + select.py)

Change `cap_hits: dict[str, tuple[str, ...]]` to use `MappingProxyType` (or
convert to `tuple[tuple[str, tuple[str, ...]], ...]`). Update `plan_tests` in
`select.py` to construct immutable versions.

### M3 — Fix nitpicks (background.py, qa.py, test file)

(a) Remove the `log_path.write_bytes(b"")` dead write.
(b) Rename criterion suffix to `" (escalation)"`.
(c) Remove the vacuous `assert int(plan.cap_impacted["a"], 16) >= 0`.

## 3. Files

| File | Module | Action |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | M1, M3b | MODIFY |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | M2 | MODIFY |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | M1, M2 | MODIFY |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | M3a | MODIFY |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py` | M3c | MODIFY |

## 4. Acceptance Criteria

- AC1: `grep -c 'cap_hits\|cap_impacted' nodes/qa.py` returns 0
- AC2: `ScopePlan.cap_hits` and `cap_impacted` are immutable mappings
- AC3: No `write_bytes(b"")` in background.py's empty-invocations branch
- AC4: Criterion suffix is `" (escalation)"`, not `" (core escalation)"`
- AC5: No vacuous hex assertion in test_cap_escalation_ledger.py
- AC6: `ruff check` passes on all modified files
- AC7: Existing tests pass
