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
> complete and `navigator-eventbus[brokers]` is installable (editable `0.1.0rc`
> is sufficient). Verify: `python -c "import navigator_eventbus.brokers"`.

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

### Target imports (from navigator-eventbus, delivered by FEAT-316)
```python
# Confirm exact exported symbol names against the INSTALLED navigator-eventbus
# before rewriting — the port may have renamed symbols on the way in.
from navigator_eventbus.brokers.redis import RedisConnection      # was navigator.brokers.redis
from navigator_eventbus.brokers.rabbitmq import RabbitMQConnection
from navigator_eventbus.brokers.sqs import SQSConnection
```

### Does NOT Exist
- ~~a production internal consumer of `navigator.brokers.*` besides the 3 examples~~
- ~~a `navigator.brokers` re-export in `navigator/__init__.py`~~ — absent
- ~~a `navigator-eventbus` dependency already declared in navigator~~ — added in
  TASK-1836; for THIS task install it editable to test the examples

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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
