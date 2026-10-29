# TASK-4877: Relocate the semantic example into `examples/agents/semantic/`

**Feature**: FEAT-769 — Example agents for the governed Semantic Layer
**Spec**: `sdd/specs/semantic-layer-example.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. Every other agent example lives under `examples/agents/`
(`a2ui/`, `aws/`, `finance/`, `oauth/`, `webbrowser/`); the semantic example is the only
one outside it. This task creates the directory the whole feature lives in, so it must
land before anything else (spec §2 Overview, Worktree Strategy).

This is a **pure move**. Spec §2 ("Why `_common.py` does not absorb the moved example")
rejects extracting its helpers: `test_example_agent.py:77-83` asserts on the moved file's
**source text**, and commit `ef85c503` already rewrote 173 of its 261 lines once after
review `issue:f0da823294fb`. A byte-identical move keeps the relocation auditable in one
`git log --follow` and holds the blast radius at two reference edits.

---

## Scope

- Move `examples/semantic/agent_semantic_example.py` to
  `examples/agents/semantic/agent_semantic_example.py` with **`git mv`**, content unchanged.
- Move `examples/semantic/README.md` to `examples/agents/semantic/README.md` with `git mv`.
- Update the one run command inside the moved README (line 3) to the new path.
- Update `_EXAMPLE_PATH` in `packages/ai-parrot-semantic/tests/test_example_agent.py:21`.
- Leave `examples/semantic/` non-existent afterwards.

**NOT in scope**: refactoring the moved example (explicitly rejected, spec §1 Non-Goals);
extracting its helpers into `_common.py` (that module is TASK-4879 and serves the NEW
examples only); rewriting the README's body (TASK-4884 merges it); any new example file;
any change under `packages/ai-parrot-semantic/src/**`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/semantic/agent_semantic_example.py` | CREATE | `git mv` target — byte-identical to the source |
| `examples/agents/semantic/README.md` | CREATE | `git mv` target, then the line-3 run command is repointed |
| `packages/ai-parrot-semantic/tests/test_example_agent.py` | MODIFY | `_EXAMPLE_PATH` gains the `"agents"` path segment |

> The two `examples/semantic/*` sources disappear as a consequence of `git mv`; do not
> delete and re-create them, or `git log --follow` stops tracing the move (AC1).

---

## Codebase Contract (Anti-Hallucination)

> Verified at `e00c8de82` (2026-10-29).

### Verified Imports

This task adds no import. The moved file's existing imports are unchanged by definition.

### Existing Signatures to Use

```python
# packages/ai-parrot-semantic/tests/test_example_agent.py:21
# occurrences of the anchor "_EXAMPLE_PATH = ": 1
_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "semantic" / "agent_semantic_example.py"

# packages/ai-parrot-semantic/tests/test_example_agent.py:27-37  — the module loader this file already uses
@pytest.fixture(scope="module")
def example() -> ModuleType:
    spec = importlib.util.spec_from_file_location("semantic_agent_example", _EXAMPLE_PATH)

# examples/semantic/README.md:3  — occurrences of "examples/semantic/agent_semantic_example.py": 1
Run `python examples/semantic/agent_semantic_example.py` with the DuckDB extra. The scripted mode requires no LLM call or network access.
```

File digests at planning time (re-verify before editing; if one differs, the file moved
under you — re-read it and correct this contract first):

```
8e04de81eaf7e712af526024bf668741cff1266b3c5a0d3adff46c0c684ecb14  packages/ai-parrot-semantic/tests/test_example_agent.py
8e2945401a662a8f2ed644c987177c199480a034d4e9c1c9586e75ee73e69ce9  examples/semantic/README.md
5cdc999fdb661fa9e49e322c46464244879ac8de7929872b40f4500abbe10e6a  examples/semantic/agent_semantic_example.py
```

`examples/semantic/agent_semantic_example.py` is 362 lines; `examples/semantic/README.md`
is 15 lines.

### Does NOT Exist

- ~~`examples/agents/semantic/`~~ — the target directory does not exist yet; `git mv` creates it.
- ~~a second reference to the old path~~ — `_EXAMPLE_PATH` (`:21`) and the README's line 3
  are the ONLY two live references. Do not go hunting for more and do not edit
  `docs/tools/semantic-layer.md` here (that is TASK-4884).
- ~~`parents[4]`~~ — the depth does NOT change. `test_example_agent.py` stays at
  `packages/ai-parrot-semantic/tests/`, so `parents[3]` is still the repo root.
- ~~a `conftest.py` in the new directory~~ — not needed, do not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/agents/semantic/agent_semantic_example.py",
      "action": "CREATE"
    },
    {
      "path": "examples/agents/semantic/README.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_example_agent.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

> No `## Delegation Contract` for this task: a delegation packet expresses a `create`
> target as a full content block, which would mean **retyping** 362 lines that must stay
> byte-identical. A `git mv` cannot be expressed that way, so this task takes the normal
> implementation route by design.

---

## Implementation Notes

### Key Constraints

- Use `git mv`, never `cp`+`rm` and never a `Write` of the file's content. AC1 requires
  `git log --follow` to trace the move and the target to be byte-identical.
- `examples/` is pytest-collected (no `testpaths`/`norecursedirs` in `pytest.ini`, no root
  `collect_ignore`; five `test_*.py` files already sit in `examples/agents/`). Do not add
  any file named `test_*.py` under `examples/` (AC10).
- `ruff check` applies to examples at line-length 120 with only `F401,F841,E402` waived
  (`ruff.toml:152`). The moved file already passes; keep it that way.

### References in Codebase

- `packages/ai-parrot-semantic/tests/test_example_agent.py:77-83` — asserts the literal
  `"_pbac.available"` is **absent** from the moved file's source text. A pure move keeps
  this true; any edit to the example risks it.

---

## Implementation Blueprint

### Steps (in order)
1. `mkdir -p examples/agents/semantic` — *why*: `git mv` will not create a missing parent directory.
2. `git mv examples/semantic/agent_semantic_example.py examples/agents/semantic/agent_semantic_example.py` — *why*: preserves rename detection so AC1's `git log --follow` holds.
3. `git mv examples/semantic/README.md examples/agents/semantic/README.md` — *why*: same, and TASK-4884 later merges this README rather than re-creating it.
4. `rmdir examples/semantic` if it survives the moves — *why*: AC1 requires the old directory to be gone.
5. Edit the moved README's line 3 and the test's line 21 — *why*: these are the only two live references to the old path (AC2).
6. Verify the example file is untouched: `git diff --cached -M --stat` must show a pure rename (`R100`) for it — *why*: a non-100 similarity means the content changed, failing AC1.

### `packages/ai-parrot-semantic/tests/test_example_agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_EXAMPLE_PATH = ' packages/ai-parrot-semantic/tests/test_example_agent.py)
# REPLACE the single line at packages/ai-parrot-semantic/tests/test_example_agent.py:21
_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "agent_semantic_example.py"
)
```
**Why**: the only edit this feature makes to an existing test (AC2). `parents[3]` is
unchanged — the test file did not move, only the example did. The line is wrapped because
the single-line form exceeds the 120-column limit once `"agents"` is inserted.

### `examples/agents/semantic/README.md` (MODIFY, after the move)
```markdown
# occurrences: 1 (verified: grep -c 'examples/semantic/agent_semantic_example.py' examples/semantic/README.md)
# REPLACE the path inside the line-3 run command (verified: examples/semantic/README.md:3)
Run `python examples/agents/semantic/agent_semantic_example.py` with the DuckDB extra. The scripted mode requires no LLM call or network access.
```
**Why**: the README's run command is the second and last live reference to the old path
(AC2). Change the path only — the rest of line 3 and every other line of this README stay
exactly as they are; TASK-4884 owns the content merge.

### FILL IN checklist
- [ ] none — every edit in this task is fully determined above.

---

## Acceptance Criteria

- [ ] `examples/agents/semantic/agent_semantic_example.py` is byte-identical to the file
      previously at `examples/semantic/` (sha256 `5cdc999f…`), and `git log --follow` traces
      the move (spec AC1).
- [ ] `examples/semantic/` no longer exists (spec AC1).
- [ ] The only edits outside the moved files are `test_example_agent.py:21` (spec AC2).
- [ ] `pytest packages/ai-parrot-semantic/tests/test_example_agent.py -q` passes unchanged.
- [ ] `ruff check examples/agents/semantic` is clean (spec AC9).
- [ ] No file named `test_*.py` was added under `examples/` (spec AC10).

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_example_agent.py -q`

---

## Test Specification

No new test. `test_example_agent.py` is the pin: its 13 existing tests must pass against
the moved path with no change other than `_EXAMPLE_PATH`. Confirm specifically that
`test_pbac_is_wired_through_a_real_guard` (`:77`) and
`test_build_toolkits_does_not_mutate_environment` (`:85`) still pass — they read the moved
file's source text and environment behaviour respectively.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer-example --feature-id FEAT-769`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none; this is the first task of the feature
4. **Verify the Codebase Contract** — re-run the three `sha256sum` lines and the two anchor
   `grep -c` counts before editing. A changed digest means the file moved under you: correct
   this contract FIRST, then implement
5. **Update status** in `sdd/tasks/index/semantic-layer-example.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — follow the Steps in order; use `git mv`, never a copy
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4877 semantic-layer-example verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
