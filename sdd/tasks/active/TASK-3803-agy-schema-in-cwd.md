# TASK-3803: Materialize the agy --json-schema file inside the sandbox-readable cwd

**Feature**: FEAT-606 — google_coding dispatcher — sandbox-readable JSON schema
**Spec**: `sdd/specs/fixgroup-1a7f930d81a4.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:e7bdce192812

---

## Context

Ledger issue `issue:e7bdce192812` (major): `GoogleCodingDispatcher` writes the
output-model schema to the host `/tmp` via `tempfile.mkstemp()` and passes it to
`agy --json-schema`. With `--sandbox`, agy can only read its workspace (the
dispatch `cwd`), so every sandboxed `google_coding` dispatch fails in ~0.2s,
before the model runs. Implements spec §2 / §3 Module 1.

---

## Scope

- Change `_materialize_json_schema` to take `cwd` and write the schema into
  `<cwd>/.dev_loop_agy/` (module constant `_SCHEMA_DIR_NAME = ".dev_loop_agy"`),
  a directory that carries its own `.gitignore` containing `*`.
- Add `_cleanup_json_schema(path)`: unlink the file; then, if the directory only
  holds the `.gitignore`, remove it. Swallow `OSError`.
- Call both from `dispatch()` (replace the inline `os.unlink` in `finally`).
- Add unit tests.

**NOT in scope**: codex/claude/gemini dispatchers; agy flags; stream parsing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | schema under cwd + cleanup helper |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` | MODIFY | new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import json      # already imported in google_coding.py
import os        # already imported in google_coding.py
import tempfile  # verified: google_coding.py:17
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py
class GoogleCodingDispatcher:                                                   # line 52
    async def dispatch(self, ...):                                              # line 126 (has `cwd: str`)
    def _build_command(self, *, profile, schema_path: str, prompt: str) -> List[str]
    def _materialize_json_schema(self, output_model: Type[BaseModel]) -> str:   # line 361
    async def _create_process(self, command: Sequence[str], cwd: str) -> Any
```

### Does NOT Exist
- ~~`GoogleCodingDispatchProfile.schema_dir`~~ — not a field; do not add one.
- ~~agy `--json-schema-inline`~~ — no such flag is used.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher._materialize_json_schema",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher.dispatch"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Self-ignoring directory, not the repo `.gitignore` — the dispatcher also
  runs against other repositories.
- Concurrent dispatches may share `cwd`: only remove the dir when empty
  apart from its `.gitignore`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_SCHEMA_DIR_NAME = ".dev_loop_agy"` at module level — *why*: one name for the dir, reused by tests.
2. Rewrite `_materialize_json_schema(output_model, cwd)` to create the dir + `.gitignore` and `mkstemp(dir=...)` — *why*: agy `--sandbox` can read only cwd.
3. Add `_cleanup_json_schema(path)` and call it from `dispatch()`'s `finally` — *why*: leave no residue in the worktree.
4. Add tests.

### `google_coding.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'schema_path = self._materialize_json_schema(output_model)' google_coding.py)
schema_path = self._materialize_json_schema(output_model, cwd)
# occurrences: 1 — replace the try/os.unlink(schema_path)/except block in finally with:
if schema_path:
    self._cleanup_json_schema(schema_path)
```

### FILL IN checklist
- [ ] `_materialize_json_schema` — write `.gitignore` only if missing; bounded by AC-2
- [ ] `_cleanup_json_schema` — rmdir only when empty but `.gitignore`; bounded by spec §7

---

## Acceptance Criteria

- [ ] `--json-schema` path is under the dispatch `cwd`
- [ ] `git status --porcelain` stays empty while the schema file exists
- [ ] Schema file and dir removed after success and after failure
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py -q`

---

## Test Specification

```python
async def test_schema_file_is_inside_cwd(dispatcher, brief, monkeypatch): ...
def test_schema_dir_is_git_ignored(dispatcher, tmp_path): ...
async def test_schema_cleaned_up_after_dispatch(dispatcher, brief, monkeypatch): ...
```

---

## Completion Note
(Agent fills this in when done)
