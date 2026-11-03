# Code Review: TASK-5098 — Table-driven rewrite of shipped SDD assets to `parrot sdd <noun> <verb>` + gates

**Spec**: sdd/specs/parrot-installer.spec.md (rev 0.10, C30 items 1, 3, 7)
**Reviewed commits**: c300c3f43d (implementation), 760b7c11a0 (pycache follow-up); fixes applied in-review: b71ca1c
**Reviewed files**: shipped assets (.claude/.agent/.agents/.codex/sdd), `parrot/sdd/audit.py`, `tests/sdd/test_no_repo_script_refs.py`, `test_installer.py`, `test_wheel_only_foreign_repo.py`, `test_audit.py`, `fixtures/asset_targets.json`
**Reviewers**: Claude (primary) + Claude code-review subagent + codex 0.164.0 (adversarial, read-only), same neutral brief
**Overall verdict**: ⚠ Approved with notes (after in-review fixes in b71ca1c; one deferred major filed)

---

## Summary

The rewrite itself is excellent: codex independently reconstructed every changed Markdown/TOML file from the
`VERBS` table (longest-first substitution) and found byte-exact agreement — arguments, continuation lines and
prose all correctly handled, prefixed modules (`sdd_meta parse` → `docs parse`, `spec_tools init-run` → `spec
init-run`) included. The gates are real checks (set-derived `_MOVED`, retired-spelling scan, 84-target
manifest-name snapshot, `(noun, verb, argv)` triples validated against `VERBS`). The one serious defect was not
in the rewrite but in the commit: a `git add -f` sweep force-added 1,016 build artifacts; the worker's follow-up
removed only the 999 `.pyc` files, leaving 17 tracked (6 `egg-info`, 9 `.so` binaries, generated
`toml.c`/`types.cpp` — 33k lines / several MB). Fixed in-review; the history-bloat residue is deferred to the
ledger for a human decision at `/sdd-done` time.

## Findings

### 🔴 Critical (fixed in-review — b71ca1c)
- **[c300c3f43d]** 17 build artifacts force-added and still tracked at HEAD: `packages/ai-parrot/src/ai_parrot.egg-info/*` (6), `parrot/codec-rs/target/release/**/*.so` (3), `parrot/utils/{parsers/toml,types}.cpython-31{1,2,3}*.so` (6), generated `parsers/toml.c` (12,078 lines) and `types.cpp` (20,936 lines). None tracked on `origin/dev`; `.gitignore` covers `*.so` / `*.egg-info/`. **Fixed**: `git rm --cached` all 17 (−36,800 lines). Found independently by all three reviewers.

### 🟡 Major (deferred — ledger)
- **[branch history]** The blobs (999 `.pyc` + 9 `.so` + 33k generated lines) remain in the branch history; a regular merge into `dev` adds them to its object store permanently. Resolution (squash-merge the PR, or rewrite + force-push the feature branch) is a human decision before `/sdd-done FEAT-633`. Filed as `issue:fb0b4b924f61`.

### 🟢 Minor (fixed in-review — b71ca1c)
- **[tests/sdd/test_no_repo_script_refs.py:109,134]** test name, docstring and assert hint still recommended the retired `parrot sdd run` spelling (codex). Renamed to `test_no_python_dash_m_helper_invocations`, hints updated to the C30 form.
- **[tests/sdd/test_no_repo_script_refs.py:184]** retired-spelling gate had no docstring and was a silent no-op on an empty glob (Claude subagent). Added docstring + `assert files` guard.
- **[parrot/sdd/audit.py:188]** new 155-col hint line (Claude subagent). Reflowed. Note: `ruff` does not enforce E501 here and two >120 lines pre-exist in the file — cosmetic, not a gate failure.

### 🟢 Minor (accepted, no action)
- **[docs/sdd/WORKFLOW.md]** edited although listed under TASK-5101's scope — mechanical, same text, disclosed in the Completion Note (both reviewers). Accepted; TASK-5101 has less to do.
- **[Completion Note / AC-4]** the "172 before == 172 after" count has no reproducible scope (task text says 87; my broad scope gives 180→180; codex's modified-files scope 171→171). The invariant holds under every scope; the absolute numbers are grep-scope artifacts.
- **[test_installer.py:266]** the pairs filter skips the `install/uninstall/status/ledger/launch` nouns, so a typo in a `parrot sdd ledger <verb>` line is not caught (Claude subagent). This is the task blueprint's own design, bounded by AC-2 — noted, not changed.

## Deferred Findings

| Severity | Title | Issue ID | Filed By |
|----------|-------|----------|----------|
| major | feat-FEAT-633 branch history carries build-artifact blobs (999 .pyc, 9 .so, 33k generated C/C++ lines) | issue:fb0b4b924f61 | Claude (review:TASK-5098) |

## Acceptance Criteria Check

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1 no `parrot sdd run` / `python -m scripts.sdd.check_spec_consequences` in shipped files | ✅ | Verified by all three reviewers (grep empty, sdd-insight excluded) |
| AC-2 gates + `check_asset_sync --check` pass | ✅ | 115 passed (my run post-fix); 123 passed (subagent, incl. twin suites); `check_asset_sync --check` exit 0 (codex + subagent) |
| AC-3 wheel-only triples run with same outcomes | ✅ | 6 passed in the worker's run; codex verified the triple/prefix mechanics by diff (`:590`); not re-run in review (slow) |
| AC-4 `wikitoolkit ledger` refs untouched | ✅ | 180 → 180 (my scope), 171 → 171 (codex's modified-files scope) |

## Adversarial Cross-Check

| Finding | Disposition | Reason |
|---------|-------------|--------|
| codex: 17 tracked build artifacts | CONFIRM | Verified vs origin/dev + .gitignore; fixed in b71ca1c |
| codex: stale `parrot sdd run` wording in test :109-110/:134 | CONFIRM | Verified in source; fixed |
| codex: wheel `check_spec_consequences` scenario accepts exit 0–3 without output check | REJECT (as must-fix) | Deliberate and documented (FEAT-784 unconfigured decision plane = controlled skip/refusal), consistent with `_ANY_CLEAN` neighbors |
| codex: pre-existing F601 at test_wheel_only_foreign_repo.py:307 | REJECT | Pre-exists c300c3f43d^; out of scope |
| Claude subagent: audit.py:188 over 120 cols | CONFIRM (cosmetic) | Only the new line exceeds; reflowed; ruff does not gate E501 |
| Claude subagent: retired-spelling gate docstring / empty-glob no-op | CONFIRM | Fixed |
| Claude subagent: pairs filter skips ledger/launch nouns | REJECT (as defect) | The task blueprint prescribes exactly this filter |
| both: docs/sdd/WORKFLOW.md scope deviation | CONFIRM (minor, accepted) | Disclosed; same text TASK-5101 would write |
| primary (retracted): first assert in `test_every_invocation_uses_parrot_sdd_run` shadowed | — | False alarm from reading two disjoint sed ranges as contiguous; full read shows each block asserts |

## Positive Highlights
- The rewrite was generated from the normative `VERBS` table and survives independent reconstruction byte-for-byte — the strongest possible evidence for a 115-file mechanical change.
- `test_rewrite_preserves_asset_names` (84-target snapshot) is exactly the "no command lost its name" proof the spec asked for.
- Deriving `_MOVED` from `mounted_modules()` removes the hand-maintained list that had already drifted three times (TASK-4088/4086/4334 annotations).
- The worker disclosed its own scope deviation and the AC-4 scope mismatch in the Completion Note instead of papering over them.
