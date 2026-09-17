# TASK-3303: Spike S2 — pytest rootdir / conftest loading for per-distribution invocations

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The kernel planner (TASK-3305) emits one pytest invocation **per distribution**
(`pytest packages/<dist>/tests/...` or `pytest tests/...`), never one spanning several (spec §2
Overview item 4, AC11). pytest picks its `rootdir`/inifile from the common ancestor of the
arguments: for `packages/ai-parrot/tests/...` that is `packages/ai-parrot/pyproject.toml`, not the
repo-root `pytest.ini`. The repo-root `conftest.py` is what makes a **worktree's** sources win over
the main-checkout editable installs ("Ensures the worktree's package sources take precedence…").
If it does not load for per-dist invocations, scoped runs in worktrees silently test main-checkout
code. Spike **S2**, risk **R6**, spec §8 open question "Root conftest loading".

---

## Scope

- From your sub-worktree (a real git worktree under `.claude/worktrees/`), run the exact probe
  commands in the blueprint for: one root `tests/` file, one `packages/ai-parrot/tests/` file, one
  `packages/ai-parrot-tools/tests/` file.
- For each, record: `rootdir`, `configfile`, whether the root `conftest.py` loaded, and from which
  path `parrot` / `parrot_tools` were imported (worktree vs main checkout).
- Try the candidate fixes (`--rootdir=<worktree>`, `-c <worktree>/pytest.ini`, `--confcutdir=<worktree>`,
  `-p conftest`-style) only as needed, and record which one restores worktree precedence **without**
  losing the distribution's own `[tool.pytest.ini_options]` (asyncio_mode, markers).
- Write the decision as an exact argv fragment the planner must add (possibly empty).

**NOT in scope**: changing any conftest, `pytest.ini` or pyproject (TASK-3316); writing the planner
(TASK-3305); any `uv sync` (forbidden in worktrees — it repoints the shared venv).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/logs/feat-563-s2-conftest-rootdir.md` | CREATE | Probe results + planner argv decision |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# none — shell probes only
```

### Existing Signatures to Use
```text
conftest.py:1-6            # repo-root conftest docstring: "Ensures the worktree's package sources take precedence over the main-repo editable installs registered via .pth files in site-packages."
pytest.ini                 # repo root: [pytest] asyncio_mode = auto; markers integration, live, real_llm, slow
packages/ai-parrot/pyproject.toml:997     # [tool.pytest.ini_options] asyncio_mode="auto"; markers real_llm, network, live
packages/ai-parrot/tests/conftest.py:15   # def pytest_collection_modifyitems(config, items)  (stubs parrot.* via sys.modules.setdefault — see root conftest docstring)
tests/sdd_scripts/test_check_task_graph.py              # small root-tree test module (probe target)
packages/ai-parrot/tests/loaders/test_chunk_documents_atomic.py  # small ai-parrot test module (probe target)
packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py  # ai-parrot-tools test module (probe target)
```

### Does NOT Exist
- ~~a `--rootdir` / `-c` convention already used by SDD agents~~ — none; that is what this spike decides
- ~~a `[tool.pytest.ini_options]` in `packages/ai-parrot-tools/pyproject.toml`~~ — none (inifile resolution may climb further)
- ~~`pytest-timeout`~~ — not installed

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "artifacts/logs/feat-563-s2-conftest-rootdir.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Evidence log: commands + trimmed output + decision. Use `--co -q` (collect only) so probes are fast.

### Key Constraints
- Run with the shared venv's pytest (`pytest` on PATH / `.venv/bin/pytest` of the main checkout); never `uv sync`.
- Use `python -c` probes or a throw-away `-p` plugin written to `/tmp` (not committed) to print `parrot.__file__`.
- The decision must keep each distribution's own ini options (asyncio_mode, markers) in effect.

### References in Codebase
- `conftest.py` (repo root) — worktree source precedence
- Spec §2 Overview item 4 (per-distribution planner), §7 R6

---

## Implementation Blueprint

### Steps (in order)
1. Confirm you are in a worktree: `git rev-parse --git-common-dir` differs from `--git-dir` — *why*: the bug only exists in worktrees.
2. Run the three `--co` probes with `-p` of a `/tmp` plugin that prints `rootdir`, `inifile`, loaded conftests and `parrot.__file__` — *why*: collection-only makes the probe cheap and exact.
3. If the root `conftest.py` is missing or `parrot` resolves outside the worktree, retry with each candidate flag and record the result — *why*: pick the minimal flag that fixes precedence.
4. Verify the chosen flag still applies the distribution's markers (`pytest --markers` output) — *why*: `--strict-markers`/asyncio behaviour must not regress.
5. Write the decision block with the exact argv fragment — *why*: TASK-3305 copies it verbatim into `planner.py`.

### `artifacts/logs/feat-563-s2-conftest-rootdir.md` (CREATE)
```markdown
# FEAT-563 spike S2 — rootdir / conftest loading per distribution

Date: <FILL IN>
Worktree: <FILL IN: git rev-parse --show-toplevel>   git-dir: <FILL IN>   common-dir: <FILL IN>

Probe plugin (not committed), /tmp/s2probe.py:

    import parrot, sys
    def pytest_collection_finish(session):
        cfg = session.config
        print("S2 rootdir=", cfg.rootpath, "inifile=", cfg.inipath)
        print("S2 conftests=", sorted(str(m.__file__) for m in cfg.pluginmanager.get_plugins() if getattr(m, "__file__", "").endswith("conftest.py")))
        print("S2 parrot=", parrot.__file__)

Command template: `PYTHONPATH=/tmp pytest -p s2probe --co -q <target> 2>&1 | grep "^S2"`

| Target | rootdir | inifile | root conftest loaded | parrot imported from | extra flag |
|---|---|---|---|---|---|
| tests/sdd_scripts/test_check_task_graph.py | <FILL IN> | | | | none |
| packages/ai-parrot/tests/loaders/test_chunk_documents_atomic.py | <FILL IN> | | | | none |
| packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py | <FILL IN> | | | | none |
| <retry rows with --rootdir / -c / --confcutdir as needed> | | | | | |

Markers still applied with the chosen flag (`pytest --markers <flag> | grep -E "real_llm|live|integration"`):
<FILL IN>

## Decision (copied verbatim by TASK-3305 into planner.py)

    PER_DIST_EXTRA_ARGS = <FILL IN: e.g. () or ("--rootdir", "{worktree}") — placeholders limited to {worktree} and {dist_root}>

Rationale: <FILL IN: 2-4 sentences>

verdict: <FILL IN: NO_FLAG_NEEDED | FLAG_REQUIRED>
```
**Why this shape**: TASK-3305 needs one exact tuple, with only `{worktree}` / `{dist_root}` substitution,
so the planner decision is mechanical. The table keeps the evidence reviewable.

### FILL IN checklist
- [ ] Probe rows for all three targets; bounded by R6
- [ ] Retry rows only if a probe shows missing root conftest or main-checkout imports
- [ ] `PER_DIST_EXTRA_ARGS` tuple; bounded by "keep the dist's own ini options" (AC8, AC11)
- [ ] verdict line

---

## Acceptance Criteria

- [ ] Log contains all three probe rows with real output, a `PER_DIST_EXTRA_ARGS` decision and a `verdict:` line
- [ ] Decision keeps worktree-source precedence and each distribution's markers (evidence in the log)
- [ ] No file other than the log is changed; no `uv sync` was run
- [ ] Resolves spec §8 "Root conftest loading" (R6) for the orchestrator

## Validation Commands

- `grep -E "^verdict: (NO_FLAG_NEEDED|FLAG_REQUIRED)$" artifacts/logs/feat-563-s2-conftest-rootdir.md`

---

## Test Specification

```bash
# Evidence task — self-check before committing:
grep -c "<FILL IN" artifacts/logs/feat-563-s2-conftest-rootdir.md   # must print 0
grep -n "PER_DIST_EXTRA_ARGS" artifacts/logs/feat-563-s2-conftest-rootdir.md
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3303-spike-conftest-rootdir.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
