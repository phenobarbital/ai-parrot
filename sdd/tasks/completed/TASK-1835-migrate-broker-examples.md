# TASK-1835: Migrate in-repo broker examples to `navigator_eventbus.brokers`

**Feature**: FEAT-318 — Navigator Brokers Removal (`navigator-eventbus` phase 5)
**Spec**: `sdd/specs/navigator-brokers-removal.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

> **CROSS-REPO**: all code changes for this task land in the sibling `navigator`
> framework repo at `/home/jesuslara/proyectos/navigator` (branch `dev`), NOT in
> ai-parrot. Use `git -C /home/jesuslara/proyectos/navigator …` or `cd` into it.
> This task file and the SDD index live in ai-parrot.
>
> **HARD BLOCKER**: do not start until FEAT-316 (`eventbus-brokers-port`) is
> complete and `navigator-eventbus[brokers]` is installable. SATISFIED —
> `navigator-eventbus 0.1.0rc1` is published on PyPI (2026-07-20), so
> `pip install "navigator-eventbus[brokers]>=0.1.0rc1"` resolves from the index.
> Verify: `python -c "import navigator_eventbus.brokers"`.

---

## Context

Spec §3 Module 1. The three `examples/brokers/nav_*_consumer.py` files are the
**only** in-repo importers of `navigator.brokers.*` (verified 2026-07-18 — no
production internal consumer exists, and `navigator/__init__.py` does not
re-export brokers). Before the origin tree can be deleted (TASK-1837), these
examples must be rewired onto the ported, PR #393-fixed package
`navigator_eventbus.brokers`. This is the first step so the later grep-neutrality
guard and test run validate a consumer-free repo.

---

## Scope

- Rewrite the imports in the three example files from `navigator.brokers.*` to
  the equivalent `navigator_eventbus.brokers.*` symbols.
- Adjust any constructor calls affected by the PR #393 signature fixes carried
  into the port:
  - **Producer `credentials`** is now keyword (was positional-required) — pass
    `credentials=...` where the example constructs a producer.
  - **Consumer kwargs** now use `.pop` semantics for
    `queue_name`/`group_name`/`consumer_name` — confirm the example's consumer
    construction still passes the right kwargs (no duplicate-arg `TypeError`).
- Confirm each example still imports and constructs cleanly against the package
  (a live broker is NOT required — an import + construct smoke is enough).

**NOT in scope**:
- Editing `pyproject.toml` (TASK-1836).
- Deleting `navigator/brokers/` (TASK-1837).
- Any change to `navigator_eventbus` code (owned by FEAT-316).
- Migrating external consumers Flowtask/FieldSync (their own repos).

---

## Files to Create / Modify

> Paths are relative to the **navigator** repo root
> (`/home/jesuslara/proyectos/navigator`).

| File | Action | Description |
|---|---|---|
| `examples/brokers/nav_redis_consumer.py` | MODIFY | imports `navigator.brokers.redis.*` → `navigator_eventbus.brokers.redis.*`; keyword `credentials` |
| `examples/brokers/nav_rabbitmq_consumer.py` | MODIFY | imports `navigator.brokers.rabbitmq.*` → `navigator_eventbus.brokers.rabbitmq.*` |
| `examples/brokers/nav_sqs_consumer.py` | MODIFY | imports `navigator.brokers.sqs.*` → `navigator_eventbus.brokers.sqs.*` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against the `navigator` repo (branch `dev`) on 2026-07-18.

### Verified source paths (navigator repo)
```
examples/brokers/nav_redis_consumer.py      # imports navigator.brokers.redis.*
examples/brokers/nav_rabbitmq_consumer.py   # imports navigator.brokers.rabbitmq.*
examples/brokers/nav_sqs_consumer.py        # imports navigator.brokers.sqs.*
```

### Target imports (VERIFIED against installed navigator-eventbus 0.1.0rc1, 2026-07-20)
```python
# The examples import the *Consumer classes (not *Connection). Symbol names are
# IDENTICAL between navigator.brokers.* and navigator_eventbus.brokers.* — the
# port preserved them, so migration is a pure module-path swap, no renames.
from navigator_eventbus.brokers.redis import RedisConsumer      # was navigator.brokers.redis.RedisConsumer
from navigator_eventbus.brokers.rabbitmq import RMQConsumer     # was navigator.brokers.rabbitmq.RMQConsumer
from navigator_eventbus.brokers.sqs import SQSConsumer          # was navigator.brokers.sqs.SQSConsumer
# Consumer __init__(self, credentials=None, timeout=5, callback=None, **kwargs)
# — examples pass only callback=<fn>, so no constructor edits are needed.
```

### Does NOT Exist
- ~~a production internal consumer of `navigator.brokers.*` besides the 3 examples~~
- ~~a `navigator.brokers` re-export in `navigator/__init__.py`~~ — absent
- ~~a `navigator-eventbus` dependency already declared in navigator~~ — added in
  TASK-1836; for THIS task install `navigator-eventbus[brokers]>=0.1.0rc1` from
  PyPI to test the examples

---

## Implementation Notes

### Verify-first
```bash
cd /home/jesuslara/proyectos/navigator
python -c "import navigator_eventbus.brokers as b; print(b.__file__)"   # must succeed
grep -rnE "navigator\.brokers" examples/brokers/                        # see current import lines
python -c "import navigator_eventbus.brokers.redis as m; print(dir(m))" # confirm real symbol names
```

### Key Constraints
- Change ONLY import statements and the constructor kwargs the #393 fixes touch.
  Do not rewrite the examples' logic or restructure them.
- Match the exact symbol names exported by the installed `navigator_eventbus`
  package — do not assume the pre-port names survived verbatim.
- Keep the examples runnable (import + construct without `TypeError`).

### References
- Spec §6 Codebase Contract (destination imports + PR #393 signature notes).
- FEAT-316 spec `sdd/specs/eventbus-brokers-port.spec.md` for the exact fixes.

---

## Acceptance Criteria

- [ ] No file under `examples/brokers/` imports `navigator.brokers.*`
      (`grep -rnE "navigator\.brokers" examples/brokers/` → zero matches).
- [ ] Each example imports from `navigator_eventbus.brokers.*` using verified
      symbol names.
- [ ] Each example imports and constructs its producer/consumer without a
      `TypeError` (PR #393 #1/#3 regression guard) — smoke check, no live broker.
- [ ] No changes outside `examples/brokers/` in the navigator repo.
- [ ] No changes to the ai-parrot repository.

---

## Test Specification

```bash
cd /home/jesuslara/proyectos/navigator
# 1. neutrality guard for this task's scope
test -z "$(grep -rnE 'navigator\.brokers' examples/brokers/)" && echo "PASS: no navigator.brokers imports"
# 2. import/construct smoke (skip-marked if a live broker is needed)
python examples/brokers/nav_redis_consumer.py --help 2>/dev/null || \
  python -c "import ast; ast.parse(open('examples/brokers/nav_redis_consumer.py').read()); print('parse OK')"
```

---

## Agent Instructions

Follow the standard SDD task flow. **Verify the Codebase Contract against the
navigator repo first** (symbol names may differ post-port). Update the per-spec
index `sdd/tasks/index/navigator-brokers-removal.json` in ai-parrot, and move
this file to `sdd/tasks/completed/` when done. Note: git commits for CODE land
in the navigator repo; the SDD state commit (index + this file move) lands in
ai-parrot on `dev`.

---

## Completion Note

**Completed by**: Claude (Opus 4.8) via `/sdd-start`
**Date**: 2026-07-20
**Notes**:
- Rewired the import line in all three `examples/brokers/nav_{redis,rabbitmq,sqs}_consumer.py`
  from `navigator.brokers.*` → `navigator_eventbus.brokers.*`. Verified against the
  installed `navigator-eventbus 0.1.0rc1` (published to PyPI 2026-07-20) that the
  class names `RedisConsumer` / `RMQConsumer` / `SQSConsumer` are **preserved** by
  the FEAT-316 port, so this was a pure 1:1 module-path swap — no symbol renames.
- **No constructor edits needed**: consumer `__init__` is
  `(credentials=None, timeout=5, callback=None, **kwargs)` and the examples pass
  only `callback=<fn>`, so the PR #393 "credentials now keyword" fix is already
  satisfied. (Task scope allowed for constructor edits; none were required.)
- Corrected the task's `## Codebase Contract` Target-imports block, which had
  guessed `*Connection` names; replaced with the verified `*Consumer` names
  (per `/sdd-start` step 7.2, stale-contract correction before implementation).
- **Acceptance**: neutrality guard → 0 `navigator.brokers` matches; all 3 examples
  import + construct (via `runpy`, `app.run()` skipped) with no `TypeError`.
- Code committed in the navigator repo worktree
  `.claude/worktrees/feat-318-navigator-brokers-removal` (commit `1124885`).
  SDD state (this file + index) committed in ai-parrot on `dev`.

**Deviations from spec**: none — symbol names differed from the spec's §6 *guess*
(`RedisConnection`), but the spec explicitly flagged those as unverified and to be
confirmed against the installed package; the verified `*Consumer` names were used.
