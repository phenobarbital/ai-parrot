# TASK-4457: Make the ingest model-detection tests hermetic against navconfig/`.env`

**Feature**: FEAT-700 — Hermetic, current expectations for the package-tree wiki tests
**Spec**: `sdd/specs/fixgroup-09687c688868.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: issue:66599d4e8c84

---

## Context

Ledger fix lane (`/sdd-fix`, fixgroup:09687c688868).
`_resolve_ingest_model_ids` (`cli.py:5247`) reads `WIKI_MODEL` /
`WIKI_LIGHTWEIGHT_MODEL` / `PARROT_NO_AUTO_LLM` through `_env_setting`
(`cli.py:585`), which resolves env **then navconfig (`.env`)**. The developer
`.env` sets `WIKI_MODEL`, so the two "both unset → detection" tests in
`TestIngestModelResolutionDetectionFallback` never reach the detection
branch (`capture == {}`). Implements spec §3 M3 (cluster D).

---

## Scope

- In `_invoke_ingest` (`test_cli.py:298`), patch `wiki_cli._env_setting`
  with an `os.environ`-only reader for the duration of the invocation.

**NOT in scope**: `cli.py` / `project.resolve_setting`; other test classes
in `test_cli.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/test_cli.py` | MODIFY | hermetic `_invoke_ingest` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki import cli as wiki_cli  # verified: test_cli.py:19
from unittest.mock import patch  # verified: test_cli.py:15
```

### Existing Signatures to Use
```python
# cli.py:585
def _env_setting(name: str) -> str | None:  # resolve_setting(name) or None — env first, then navconfig
# cli.py:5247
def _resolve_ingest_model_ids(lightweight_model_opt, model_opt) -> tuple[str, str]:  # uses _env_setting for the three vars
# test_cli.py:298
    def _invoke_ingest(self, project: Path, capture: dict):  # patches wiki_cli._build_triage_adapters, invokes `ingest ... --dry-run`
```

### Does NOT Exist
- ~~`monkeypatch.delenv("WIKI_MODEL")` isolating the test~~ — the value
  comes from navconfig, not the process env.
- ~~`import os` in test_cli.py~~ — add it (verified absent at `test_cli.py:13-20`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_cli.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_env_setting",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_ingest_model_ids"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The reader must return `None` for missing **and empty** values so the
  "both unset" branch is reached (`resolve_setting` preserves `""`).
- The three env-driven tests in the class (`test_opt_out_disables_detection`,
  `test_only_one_set_does_not_autodetect`, `test_explicit_both_set_does_not_autodetect`)
  set their variables with `monkeypatch.setenv`, so the env-only reader keeps
  them green.

---

## Implementation Blueprint

### `packages/ai-parrot/tests/knowledge/wiki/test_cli.py` (MODIFY)
```python
# add `import os` to the stdlib imports (after `import json`, test_cli.py:13)

# occurrences: 1 (verified: grep -c 'def _invoke_ingest' <path>)
# REPLACE the `_invoke_ingest` helper (lines 298-312):
    def _invoke_ingest(self, project: Path, capture: dict):
        def _fake_build_triage_adapters(lightweight_model, model):
            capture["lightweight_model"] = lightweight_model
            capture["model"] = model
            raise RuntimeError("stop-after-resolution")

        def _env_only(name: str) -> str | None:
            # Hermetic: `_env_setting` falls back to navconfig (.env), where a
            # developer WIKI_MODEL would silently skip the detection branch.
            return os.environ.get(name) or None

        with (
            patch.object(wiki_cli, "_build_triage_adapters", side_effect=_fake_build_triage_adapters),
            patch.object(wiki_cli, "_env_setting", side_effect=_env_only),
        ):
            runner = CliRunner()
            return runner.invoke(
                wiki,
                ["ingest", str(project), "--path", str(project), "--dry-run"],
            )
```

---

## Acceptance Criteria

- [ ] AC1: all five `TestIngestModelResolutionDetectionFallback` tests pass
      with `WIKI_MODEL` present in the repo `.env` (not exported).
- [ ] AC2: they also pass with `WIKI_MODEL` exported? — **No**: exported env
      is an explicit override by design; AC1 is the hermeticity target.
- [ ] No linting errors.

---

## Validation Commands

- `pytest "packages/ai-parrot/tests/knowledge/wiki/test_cli.py::TestIngestModelResolutionDetectionFallback" -q -p no:cacheprovider -o addopts=""`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q -p no:cacheprovider -o addopts=""`

---

## Test Specification

See blueprint (helper change only).

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-09687c688868 --feature-id FEAT-700`)
2. **Read the spec** for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/fixgroup-09687c688868.json` → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the one listed file
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4457 fixgroup-09687c688868 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: agent:sdd-fix (delegated coder, diff reviewed)
**Date**: 2026-10-18
**Notes**: _invoke_ingest patches wiki_cli._env_setting with an os.environ-only
reader, so the developer .env (WIKI_MODEL set, not exported) no longer skips the
detection branch. Class 5 passed; whole file 19 passed.

**Deviations from spec**: none.

