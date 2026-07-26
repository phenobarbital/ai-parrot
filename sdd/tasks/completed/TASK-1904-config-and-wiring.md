# TASK-1904: Config keys + server wiring for adversarial/parallel review

**Feature**: FEAT-375 — Codex CLI Adversarial Second-Opinion Agent
**Spec**: `sdd/specs/codex-cli-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1902, TASK-1903
**Assigned-to**: unassigned

---

## Context

Module 6 of FEAT-375 (spec §3). Makes the new dispatchers selectable by
operators: conf keys + the demo-server bootstrap that FEAT-270 (TASK-1698)
established as the factory-creation site.

⚠️ **`parrot/conf.py` has uncommitted in-flight FEAT-374 edits in the main
checkout.** This task runs in the feature worktree (clean copy), but to keep
the eventual merge trivial: add settings **append-only at the end of the
dev-loop section** (after `DEV_LOOP_ACTIONS_RETENTION_DAYS`, conf.py:976-978).
Do NOT reflow or touch existing lines.

---

## Scope

- MODIFY `packages/ai-parrot/src/parrot/conf.py` (append-only, after :978):
  - `DEV_LOOP_ADVERSARIAL_MODEL: str` — default `"gpt-5.5"`.
  - `DEV_LOOP_ADVERSARIAL_SCOPE: str` — default `"uncommitted"`.
  - `DEV_LOOP_CODEREVIEW_JUDGE: bool` — default `False` (`config.getboolean`,
    match existing bool patterns in the file).
  - `DEV_LOOP_GATE_TTL_REVIEW_ESCALATION: int` — default `86400`
    (comment: fail-closed; mirror `DEV_LOOP_GATE_TTL_*` comment style :954-972).
  - Update the `DEV_LOOP_CODEREVIEW_AGENT` comment (:927-929) to list the two
    new values — comment-only edit of an existing block; keep it minimal.
- MODIFY `examples/dev_loop/server.py` (the FEAT-270 bootstrap site):
  - `"codex-adversarial"` selection → build `CodexCodeDispatcher` (reuse the
    existing codex construction path) → `CodeReviewDispatcherFactory.create(
    "codex-adversarial", dispatcher=..., model=conf.DEV_LOOP_ADVERSARIAL_MODEL,
    review_scope=conf.DEV_LOOP_ADVERSARIAL_SCOPE)`.
  - `"parallel"` selection → build primary (claude-code reviewer, existing
    path) + adversary (codex-adversarial) → `create("parallel", primary=...,
    adversary=..., judge_enabled=conf.DEV_LOOP_CODEREVIEW_JUDGE,
    judge_dispatcher=<primary's underlying dispatcher when judge enabled>)`.
- Replace the `getattr(conf, "...", fallback)` shims introduced by
  TASK-1902/1903 with direct `conf.X` references now that the keys exist.
- Unit tests for defaults (see Test Specification).

**NOT in scope**: touching FEAT-374's in-flight edits; `parrot/cli/devloop/`;
dispatcher/QANode logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | 4 new keys, append-only + 1 comment update |
| `examples/dev_loop/server.py` | MODIFY | reviewer selection branches |
| `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | MODIFY | drop getattr shim → conf.X |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | drop getattr shim → conf.X |
| `packages/ai-parrot/tests/flows/dev_loop/test_adversarial_conf.py` | CREATE | defaults tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-26 on `dev` @ `ec6e0432a`.

### Verified Imports
```python
from parrot import conf                       # pattern used in code_review.py:19
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory  # code_review.py:104
```

### Existing Signatures to Use
```python
# conf.py:923-932 — existing reviewer selection block (comment update only)
DEV_LOOP_CODEREVIEW_MODEL: str = config.get("DEV_LOOP_CODEREVIEW_MODEL", fallback="claude-sonnet-4-6")
DEV_LOOP_CODEREVIEW_AGENT: str = config.get("DEV_LOOP_CODEREVIEW_AGENT", fallback="claude-code")

# conf.py:961-972 — gate TTL pattern to mirror
DEV_LOOP_GATE_TTL_DEPLOYMENT: int = config.getint("DEV_LOOP_GATE_TTL_DEPLOYMENT", fallback=86400)

# conf.py:976-978 — current end of the dev-loop section (append AFTER this)
DEV_LOOP_ACTIONS_RETENTION_DAYS: int = config.getint("DEV_LOOP_ACTIONS_RETENTION_DAYS", fallback=7)

# examples/dev_loop/server.py — FEAT-270 TASK-1698 bootstrap:
# selects reviewer via conf.DEV_LOOP_CODEREVIEW_AGENT and
# CodeReviewDispatcherFactory.create(...). READ this file first; extend the
# existing if/elif selection, do not restructure it.
```

### Does NOT Exist
- ~~the 4 new conf keys~~ — this task creates them.
- ~~`config.getbool`~~ — verify the exact boolean getter name used elsewhere in conf.py (`getboolean`/`getbool`) before use; follow the file's existing usage.
- ~~reviewer wiring in `factories.py`~~ needing changes — `codereview_dispatcher` already flows through (factories.py:53→140); only the SERVER selection branch is extended.
- ~~`parrot/cli/devloop/` involvement~~ — FEAT-374 territory, out of scope.

---

## Implementation Notes

### Key Constraints
- **Append-only in conf.py** — merge-conflict avoidance with FEAT-374.
- Comment style: mirror the FEAT-270/322 comment blocks around :927/:954.
- server.py: keep the single-reviewer default path untouched.

### References in Codebase
- `sdd/tasks/completed/TASK-1698-factory-wiring-server-bootstrap.md` — how FEAT-270 wired the three reviewers

---

## Acceptance Criteria

- [ ] All 4 keys importable from `parrot.conf` with specified defaults
- [ ] `DEV_LOOP_CODEREVIEW_AGENT=codex-adversarial` boots the demo server with the advisory reviewer
- [ ] `DEV_LOOP_CODEREVIEW_AGENT=parallel` boots with the composite (judge off by default)
- [ ] No `getattr(conf, ...)` shims remain in code_review.py / qa.py
- [ ] conf.py diff is purely additive after line 978 (+1 comment edit at :927-929)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_adversarial_conf.py -v` passes; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_adversarial_conf.py
def test_conf_defaults(monkeypatch):
    from parrot import conf
    assert conf.DEV_LOOP_ADVERSARIAL_MODEL == "gpt-5.5"
    assert conf.DEV_LOOP_ADVERSARIAL_SCOPE == "uncommitted"
    assert conf.DEV_LOOP_CODEREVIEW_JUDGE is False
    assert conf.DEV_LOOP_GATE_TTL_REVIEW_ESCALATION == 86400
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 6, §7 conf.py risk)
2. **Check dependencies** — TASK-1902, TASK-1903 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract**; READ `examples/dev_loop/server.py` selection block first
4. **Update status** in `sdd/tasks/index/codex-cli-agent.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

Implemented exactly as specified:

- `conf.py`: 4 new keys appended strictly after
  `DEV_LOOP_ACTIONS_RETENTION_DAYS` (:976-978) —
  `DEV_LOOP_ADVERSARIAL_MODEL` (`"gpt-5.5"`), `DEV_LOOP_ADVERSARIAL_SCOPE`
  (`"uncommitted"`), `DEV_LOOP_CODEREVIEW_JUDGE` (`config.getboolean`,
  `False`), `DEV_LOOP_GATE_TTL_REVIEW_ESCALATION` (`config.getint`,
  `86400`, comment mirrors the `DEV_LOOP_GATE_TTL_*` style at :961-972).
  Plus the one instructed comment-only edit at `DEV_LOOP_CODEREVIEW_AGENT`
  (:927-929) listing the two new agent values. `git diff conf.py` confirms
  the change is exactly that: one comment edit + a purely additive block
  after line 978 (verified — no existing lines reflowed).
- `code_review.py` / `qa.py`: both `getattr(conf, "...", fallback)` shims
  from TASK-1902/1903 replaced with direct `conf.DEV_LOOP_ADVERSARIAL_MODEL`
  / `conf.DEV_LOOP_GATE_TTL_REVIEW_ESCALATION` references (verified no
  occurrences remain via `test_no_getattr_conf_shims_remain`).
- `examples/dev_loop/server.py`: extended the existing
  `codereview_agent` if/elif chain (read `server.py` first per
  instructions) with two new branches, keeping the original three
  (`claude-code`/`codex`/`gemini`) byte-identical:
  - `"codex-adversarial"`: reuses the existing codex-dispatcher-reuse
    pattern (share `development_dispatcher` when it's already a
    `CodexCodeDispatcher`, else build one), then
    `CodeReviewDispatcherFactory.create("codex-adversarial", dispatcher=...,
    model=conf.DEV_LOOP_ADVERSARIAL_MODEL,
    review_scope=conf.DEV_LOOP_ADVERSARIAL_SCOPE)`.
  - `"parallel"`: builds `primary = create("claude-code", dispatcher=dispatcher)`
    and `adversary = create("codex-adversarial", ...)` (same construction as
    above), then `create("parallel", primary=..., adversary=...,
    judge_enabled=conf.DEV_LOOP_CODEREVIEW_JUDGE, judge_dispatcher=dispatcher
    if conf.DEV_LOOP_CODEREVIEW_JUDGE else None)`.
  - Mechanism note: since these two new agents build `codereview_dispatcher`
    directly (their factory kwargs don't fit the old branches' single
    `dispatcher=` tail call), introduced `codereview_dispatcher: object |
    None = None` before the chain; the tail call
    (`CodeReviewDispatcherFactory.create(codereview_agent_key,
    dispatcher=codereview_underlying_dispatcher)`) now only fires
    `if codereview_dispatcher is None`, i.e. unchanged for the 3 original
    agents. `RuntimeError` message updated to list all 5 valid values.
  - **Flagged caveat** (inherited from TASK-1902's own flagged ambiguity):
    `judge_dispatcher=dispatcher` wires the raw `ClaudeCodeDispatcher`
    instance, whose real `.dispatch()` signature requires `profile=`/
    `output_model=` that `ParallelPerspectiveReviewDispatcher._run_judge()`
    does not pass. This is the literal wiring the task specifies
    ("judge_dispatcher=<primary's underlying dispatcher when judge
    enabled>"), and `DEV_LOOP_CODEREVIEW_JUDGE` defaults to `False` so this
    path is inert unless an operator explicitly opts in — but opting in
    today would raise a `TypeError` on the judge dispatch (which
    `ParallelPerspectiveReviewDispatcher.review()` already catches and
    degrades silently per its own contract, so it wouldn't crash the run,
    just silently never produce a judge summary). Surfacing this now in
    case a future task wants to introduce a dedicated judge-adapter type
    instead of reusing the raw dev dispatcher.
- `test_adversarial_conf.py`: the Test Specification's `test_conf_defaults`
  plus 2 extra — a type-correctness check and a regression test asserting
  no `getattr(conf, "DEV_LOOP_ADVERSARIAL_MODEL"/"DEV_LOOP_GATE_TTL_REVIEW_ESCALATION", ...)`
  shim text remains in either module's source.

Verification: `pytest packages/ai-parrot/tests/flows/dev_loop/ -q` →
648 passed, 1 pre-existing failure (`test_models_module_is_pure`, same
known ordering-pollution issue noted in TASK-1899-1903), 5 skipped.
`ruff check` clean on all 5 touched files (a pre-existing,
unrelated `E402` at `conf.py:450` — verified present before this task's
changes via `git stash` — is untouched by this diff).
`python -c "import ast; ast.parse(...)"` confirms `server.py` parses
cleanly (no aiohttp app boot needed for that check).

No divergence from the task spec; no files touched outside the declared
list.
