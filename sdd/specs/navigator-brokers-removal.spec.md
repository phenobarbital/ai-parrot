---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Navigator Brokers Removal (`navigator-eventbus` phase 5)

**Feature ID**: FEAT-318
**Date**: 2026-07-18
**Author**: Jesus (phenobarbital) + Claude
**Status**: approved
**Target version**: navigator (framework) — next minor release

> **Phase 5 of 5** of the EventBus extraction plan defined in
> `sdd/proposals/navigator-eventbus-extraction.brainstorm.md`.
> Prior phases:
> - Phase 1: `eventbus-core-extraction` (**FEAT-312**) — bus core → `navigator-eventbus`.
> - Phase 2: `eventbus-lifecycle-extraction` (**FEAT-313**) — lifecycle machinery.
> - Phase 3: `eventbus-brokers-port` (**FEAT-316**) — ported `navigator.brokers` →
>   `navigator_eventbus.brokers` with the PR #393 fixes and navconfig desacople.
> - Phase 4: `parrot-eventbus-migration` (**FEAT-317**) — rewires ai-parrot onto
>   the `navigator-eventbus` package.
>
> **Blocking dependency**: this phase deletes the *origin* copy of the brokers
> and therefore MUST NOT start until **FEAT-316 is complete and
> `navigator-eventbus[brokers]` is installable** (editable `0.1.0rc` is
> sufficient). FEAT-317 does not block this phase technically (different repo),
> but the coordinated release ordering below assumes it is done or in flight.
>
> **Cross-repo note**: this spec artifact lives in ai-parrot's SDD tree for
> continuity with phases 1–4, but **all code changes land in the sibling
> `navigator` framework repo** (`/home/jesuslara/proyectos/navigator`, branch
> `dev`). See §Worktree Strategy. No ai-parrot source is modified by this phase.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Phase 3 (FEAT-316) ported the entire `navigator/brokers/` tree (~2,197 LOC) into
`navigator_eventbus.brokers`, applying the three PR
[navigator#393](https://github.com/phenobarbital/navigator/pull/393) fixes and
decoupling the layer from the navigator framework (auth, `BaseApplication`,
`navigator.conf`, `ValidationError`). At the close of phase 3 there are **two
copies of the broker code**: the canonical, fixed copy in `navigator-eventbus`,
and the now-stale, buggy original still living in the `navigator` framework at
`navigator/brokers/`.

Keeping the origin copy is actively harmful:

- It still carries the three PR #393 bugs (RedisConsumer kwargs `TypeError`, PEL
  starvation / no `XAUTOCLAIM`, positional-required producer credentials).
- It drags `aiormq` into the navigator dependency set solely to service brokers.
- It invites divergence: any consumer importing `navigator.brokers.*` gets the
  unfixed code path, while consumers on `navigator_eventbus.brokers` get the
  fixed one — a silent correctness fork.

This phase eliminates the fork by **deleting `navigator/brokers/` entirely** (no
compatibility shim — resolved in brainstorm), migrating the only in-repo
consumers (three examples), and dropping the now-orphaned `aiormq` dependency.
The migration is intentionally *hard*: consumers must move to
`navigator_eventbus.brokers`. PR #393 is closed referencing this migration.

### Goals

- Delete the complete `navigator/brokers/` package (18 files, ~2,197 LOC) from
  the `navigator` framework repo.
- Migrate the three in-repo consumers
  (`examples/brokers/nav_{redis,rabbitmq,sqs}_consumer.py`) to import from
  `navigator_eventbus.brokers.*` and keep them runnable.
- Add `navigator-eventbus` (extra `[brokers]`) as an **optional extra** in
  navigator's `pyproject.toml` so example/consumer usage opts in explicitly.
- Drop the now-unused `aiormq` direct dependency from navigator's
  `pyproject.toml` (verified used *only* by `navigator/brokers/`).
- Confirm `navigator/__init__.py` and other public surfaces no longer reference
  `navigator.brokers` (already true — no re-export exists).
- Close/annotate PR #393 to reference the port + removal, and record the
  coordinated-release requirement for external consumers (Flowtask, FieldSync).

### Non-Goals (explicitly out of scope)

- **Any change to `navigator-eventbus` code** — the fixed brokers already
  shipped in phase 3 (FEAT-316). This phase only *deletes the origin* and
  rewires navigator's own imports.
- **Any change to ai-parrot** — ai-parrot's own migration is phase 4 (FEAT-317);
  no ai-parrot source is touched here.
- **Migrating external consumers (Flowtask, FieldSync)** — those live in their
  own repos and adopt `navigator_eventbus.brokers` via their own specs. This
  phase only *coordinates* the release ordering and documents the break.
- **A compatibility shim / re-export** at `navigator.brokers` — explicitly
  rejected in brainstorm (hard migration, no shim).
- **Dropping `aioboto3` or `redis`** from navigator — both are used outside
  `brokers/` (`navigator/utils/file/s3.py`; `navigator/ext/redis/`,
  `navigator/background/tracker/redis.py`) and MUST remain.

---

## 2. Architectural Design

### Overview

A deletion-and-rewire operation confined to the `navigator` framework repo. The
canonical broker implementation already lives in `navigator_eventbus.brokers`
(phase 3). This phase removes the duplicate origin tree, points the only in-repo
consumers at the package, and prunes the dependency navigator no longer needs.

Because navigator has **no production internal consumers** of
`navigator.brokers.*` (verified: only `examples/brokers/*` import it, and
`navigator/__init__.py` does not re-export brokers), the blast radius inside the
repo is small. The breaking impact is external — Flowtask and FieldSync import
`navigator.brokers.*` — and is managed by release coordination, not by code in
this repo.

### Component Diagram

```
BEFORE (two copies):
  navigator/brokers/*  ──(unfixed, aiormq)──►  Flowtask / FieldSync / examples
  navigator_eventbus.brokers/*  ──(PR#393-fixed)──►  ai-parrot (phase 4)

AFTER (single source):
  navigator_eventbus.brokers/*  ──(PR#393-fixed)──►  examples (migrated)
                                                 ──►  Flowtask / FieldSync (coordinated)
                                                 ──►  ai-parrot (phase 4)
  navigator/brokers/  ──►  DELETED
  navigator pyproject:  - aiormq  ;  + navigator-eventbus[brokers] (extra)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator/brokers/` (framework) | **deletes** | entire package removed, no shim |
| `examples/brokers/nav_*_consumer.py` | modifies | imports rewired to `navigator_eventbus.brokers.*` |
| `navigator/pyproject.toml` | modifies | drop `aiormq`; add optional extra `[brokers]` = `navigator-eventbus[brokers]` |
| `navigator/__init__.py` | verify (no-op expected) | already has no `brokers` re-export |
| Flowtask / FieldSync (external repos) | coordinated release | migrate imports to `navigator_eventbus.brokers.*` before navigator ships; FieldSync drops its local #393 shim |
| PR navigator#393 | closes / annotates | fixes landed in `navigator_eventbus`; PR closed referencing migration |

### Data Models

No new data models. This phase deletes code and edits dependency metadata.

### New Public Interfaces

None. The public broker interface now lives in `navigator_eventbus.brokers`
(delivered by FEAT-316); this phase removes the origin surface only.

---

## 3. Module Breakdown

> Work happens in the `navigator` repo. Paths below are relative to that repo
> root (`/home/jesuslara/proyectos/navigator`).

### Module 1: Migrate in-repo examples
- **Path**: `examples/brokers/nav_redis_consumer.py`,
  `examples/brokers/nav_rabbitmq_consumer.py`,
  `examples/brokers/nav_sqs_consumer.py`
- **Responsibility**: Replace `from navigator.brokers.* import …` with the
  equivalent `from navigator_eventbus.brokers.* import …`; adjust any
  constructor calls affected by the PR #393 signature fixes (producer
  `credentials` now keyword; consumer kwargs `.pop` semantics).
- **Depends on**: `navigator-eventbus[brokers]` installed.

### Module 2: Dependency metadata
- **Path**: `pyproject.toml`
- **Responsibility**: Remove the `aiormq>=6.8.1` direct dependency (used only by
  the deleted brokers); remove/clean the `aiormq.*` mypy override if present; add
  an optional extra `[brokers]` pinning `navigator-eventbus[brokers]`.
- **Depends on**: Module 1 (examples now consume the extra).

### Module 3: Delete the origin brokers tree
- **Path**: `navigator/brokers/` (whole directory — 18 `.py` files)
- **Responsibility**: `git rm -r navigator/brokers/`. Verify no remaining import
  of `navigator.brokers` anywhere in the repo after deletion.
- **Depends on**: Modules 1 & 2 (nothing in-repo imports it anymore).

### Module 4: Public-surface & release coordination
- **Path**: `navigator/__init__.py` (verify), PR #393, release notes / CHANGELOG
- **Responsibility**: Confirm no public re-export references brokers; annotate
  and close PR #393 referencing the port+removal; document the breaking change
  and the coordinated-release requirement for Flowtask/FieldSync in the
  changelog / migration note.
- **Depends on**: Module 3.

---

## 4. Test Specification

> The navigator repo's own suite must stay green after removal. There is no new
> broker behavior to test here (behavior is owned by `navigator-eventbus`, tested
> under FEAT-316).

### Unit Tests
| Test | Module | Description |
|---|---|---|
| navigator existing suite | repo-wide | Full `pytest` run passes with `navigator/brokers/` deleted (no import errors, no collection errors) |
| import-neutrality guard | Module 3 | `grep -rE "navigator\.brokers" navigator/ examples/` returns **zero** matches after migration |
| example smoke (redis) | Module 1 | `examples/brokers/nav_redis_consumer.py` imports and constructs against `navigator_eventbus.brokers` without `TypeError` (PR #393 #1/#3 regression guard) |

### Integration Tests
| Test | Description |
|---|---|
| editable install | `uv pip install -e .[brokers]` in navigator resolves `navigator-eventbus[brokers]` and imports `navigator_eventbus.brokers.{redis,rabbitmq,sqs}` |
| dependency prune | `aiormq` no longer appears as a navigator direct dependency; `aioboto3`/`redis` still resolve (still used elsewhere) |

### Test Data / Fixtures
No new fixtures. Reuse existing broker connection fixtures from
`navigator-eventbus` where an example smoke test needs a live broker (skip-marked
when no broker is available, matching the navigator repo's existing convention).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `navigator/brokers/` is deleted from the navigator repo (all 18 files gone).
- [ ] No file under `navigator/` or `examples/` imports `navigator.brokers.*`
      (verified by grep guard returning zero matches).
- [ ] The three `examples/brokers/nav_*_consumer.py` import from
      `navigator_eventbus.brokers.*` and run/import cleanly.
- [ ] `navigator`'s `pyproject.toml` no longer lists `aiormq` as a direct
      dependency; the `aiormq.*` tooling override (if any) is removed.
- [ ] `navigator`'s `pyproject.toml` exposes an optional extra `[brokers]`
      resolving to `navigator-eventbus[brokers]`; `uv pip install -e .[brokers]`
      succeeds.
- [ ] `aioboto3` and `redis` remain present and functional (still used by
      `navigator/utils/file/s3.py`, `navigator/ext/redis/`,
      `navigator/background/tracker/redis.py`).
- [ ] Navigator's existing test suite passes (`pytest`) with no
      collection/import errors introduced by the removal.
- [ ] PR navigator#393 is annotated/closed referencing the port + removal.
- [ ] A migration/breaking-change note documents that `navigator.brokers.*`
      consumers must move to `navigator_eventbus.brokers.*` and records the
      coordinated-release requirement (Flowtask, FieldSync).
- [ ] No changes were made to the ai-parrot repository.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references below were verified against the sibling `navigator` repo at
> `/home/jesuslara/proyectos/navigator` (branch `dev`) on 2026-07-18.
> Line-level signatures are owned by phase 3 (FEAT-316) in `navigator-eventbus`;
> this phase does not re-implement them.

### Verified Imports (post-migration target — from `navigator-eventbus`, FEAT-316)
```python
# Destination package (delivered by FEAT-316). Exact symbol names to be
# confirmed against the installed navigator-eventbus 0.1.0rc before rewiring:
from navigator_eventbus.brokers.redis import RedisConnection      # port of navigator.brokers.redis
from navigator_eventbus.brokers.rabbitmq import RabbitMQConnection
from navigator_eventbus.brokers.sqs import SQSConnection
```

### Files to Delete (verified present in navigator repo)
```
navigator/brokers/__init__.py
navigator/brokers/connection.py
navigator/brokers/consumer.py
navigator/brokers/producer.py
navigator/brokers/wrapper.py
navigator/brokers/pickle.py
navigator/brokers/redis/__init__.py
navigator/brokers/redis/connection.py
navigator/brokers/redis/consumer.py
navigator/brokers/redis/producer.py
navigator/brokers/rabbitmq/__init__.py
navigator/brokers/rabbitmq/connection.py
navigator/brokers/rabbitmq/consumer.py
navigator/brokers/rabbitmq/producer.py
navigator/brokers/sqs/__init__.py
navigator/brokers/sqs/connection.py
navigator/brokers/sqs/consumer.py
navigator/brokers/sqs/producer.py
# total: 18 files, ~2,197 LOC (verified via wc -l on 2026-07-18)
```

### In-repo Consumers to Migrate (verified — the ONLY in-repo importers)
```
examples/brokers/nav_redis_consumer.py
examples/brokers/nav_rabbitmq_consumer.py
examples/brokers/nav_sqs_consumer.py
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| migrated examples | `navigator_eventbus.brokers.*` | import rewrite | `examples/brokers/*` (navigator repo) |
| `pyproject [brokers]` | `navigator-eventbus[brokers]` | optional extra | `navigator/pyproject.toml` |
| `aiormq` removal | (nothing else uses it) | dep prune | grep: only `navigator/brokers/` used `aiormq` |

### Does NOT Exist (Anti-Hallucination)
- ~~`navigator/__init__.py` re-export of `brokers`~~ — verified absent (grep: no
  `broker` mention in `navigator/__init__.py`); deletion does not break the
  package's public `__init__`.
- ~~production internal consumers of `navigator.brokers.*` inside navigator~~ —
  do not exist; only `examples/brokers/*` import it.
- ~~a `navigator-eventbus` dependency already in navigator `pyproject.toml`~~ —
  does not exist yet; this phase adds it as the `[brokers]` extra.
- ~~`aiormq` usage outside `navigator/brokers/`~~ — none (safe to drop).
- **Counter-anchor**: `aioboto3` IS used at `navigator/utils/file/s3.py` and
  `redis` at `navigator/ext/redis/`, `navigator/background/tracker/redis.py` —
  these are NOT droppable. Do not remove them.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Execute all changes in the `navigator` repo, on branch `dev` (see Worktree
  Strategy). Run `git -C /home/jesuslara/proyectos/navigator …` from ai-parrot
  or `cd` into the navigator repo.
- Migrate examples first, prune deps second, delete `navigator/brokers/` last —
  so the grep-neutrality guard and test run validate a consumer-free state.
- Keep the deletion a clean `git rm -r navigator/brokers/` (one logical commit)
  for bisectability.
- Preserve the navigator repo's existing extras/formatting conventions when
  editing `pyproject.toml`.

### Known Risks / Gotchas
- **External breakage (by design)**: Flowtask and FieldSync import
  `navigator.brokers.*`. This phase ships a *breaking* navigator release with no
  shim. Mitigation: coordinate the navigator release with those repos' import
  migrations; FieldSync must drop its local PR #393 shim in the same window.
- **PR #393 provenance**: the fixes are already in `navigator-eventbus`
  (FEAT-316). Do not re-apply them here; just close/annotate the PR to avoid a
  dangling "unmerged fix" impression.
- **`aiormq` mypy/tooling override**: navigator's `pyproject.toml` has an
  `aiormq.*` entry (line ~293) likely in a mypy overrides block — remove it
  alongside the dependency to avoid a dead override.
- **navigator-eventbus availability**: the `[brokers]` extra must resolve. During
  development this is the editable `0.1.0rc`; ensure the version pin in
  navigator's pyproject matches what FEAT-316 publishes (editable or PyPI).
- **Symbol-name drift**: confirm the exact exported class names in
  `navigator_eventbus.brokers.*` against the installed package before rewriting
  example imports — the port may have renamed on the way in.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-eventbus[brokers]` | `>=0.1.0rc` (match FEAT-316) | new optional extra `[brokers]`; provides the ported brokers |
| `aiormq` | — | **removed** from navigator (only brokers used it) |
| `aioboto3`, `redis` | unchanged | retained — used outside `brokers/` |

---

## 8. Open Questions

> Resolved items carried forward from
> `sdd/proposals/navigator-eventbus-extraction.brainstorm.md` and this spec's
> clarifying round (2026-07-18).

- [x] Compatibility shim at `navigator.brokers` after removal? — *Resolved in
  brainstorm*: **No** — delete `navigator/brokers/` and migrate consumers (hard
  migration, coordinated release).
- [x] How do PR #393 fixes land? — *Resolved in brainstorm*: directly in the
  `navigator-eventbus` port (phase 3, with the contributor's tests); PR #393 is
  closed referencing the migration.
- [x] Where does this spec live / what branch? — *Resolved 2026-07-18*: authored
  in ai-parrot's SDD tree (`type: feature`, `base_branch: dev`) for continuity
  with phases 1–4; **implementation executes in the `navigator` repo on `dev`**;
  no ai-parrot worktree.
- [x] What happens to `examples/brokers/*` and does navigator gain a
  `navigator-eventbus` dependency? — *Resolved 2026-07-18*: **migrate** the three
  examples to `navigator_eventbus.brokers.*` and add `navigator-eventbus[brokers]`
  as an optional extra in navigator's `pyproject.toml`; drop `aiormq`.
- [ ] Exact version pin for the `[brokers]` extra — depends on whether FEAT-316
  publishes to PyPI before this phase runs (editable `0.1.0rc` vs released
  version). — *Owner: Jesus* (decide at implementation time).
- [ ] Release-coordination window with Flowtask/FieldSync — who cuts the
  navigator release and confirms both consumers have migrated. — *Owner: Jesus*.

---

## Worktree Strategy

**Default isolation unit**: `per-spec` (sequential tasks) — **but in the
`navigator` repo, not ai-parrot.**

- All code changes for this feature happen in the sibling `navigator` framework
  repo (`/home/jesuslara/proyectos/navigator`, branch `dev`). ai-parrot source
  is untouched.
- The task sequence is inherently ordered (migrate examples → prune deps →
  delete tree → coordinate release) and small, so a single sequential worktree
  in the navigator repo is appropriate:
  ```bash
  git -C /home/jesuslara/proyectos/navigator checkout dev
  git -C /home/jesuslara/proyectos/navigator worktree add -b feat-318-navigator-brokers-removal \
    .claude/worktrees/feat-318-navigator-brokers-removal HEAD
  ```
  (Adjust to the navigator repo's own worktree/branch conventions if they differ.)
- The SDD state (this spec, its per-spec task index) is committed in **ai-parrot**
  on `dev`; the *code* commits land in **navigator**. `/sdd-done` bookkeeping
  applies to the ai-parrot artifact only — the navigator PR is opened in that
  repo separately.

**Cross-feature dependencies (must be merged/available first)**:
- FEAT-316 `eventbus-brokers-port` — **hard blocker**: `navigator-eventbus[brokers]`
  must be installable before the origin can be deleted.
- FEAT-317 `parrot-eventbus-migration` — not a technical blocker for this repo,
  but part of the same coordinated cutover; ensure ai-parrot is off
  `navigator.brokers` before external consumers are pushed to migrate.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-18 | Jesus + Claude | Initial draft — phase 5 of eventbus extraction; scope resolved via brainstorm carry-forward + navigator-repo research + clarifying round |
