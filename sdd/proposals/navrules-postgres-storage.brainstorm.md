---
type: feature
base_branch: dev
---

# Brainstorm: Promote `PostgresRuleStorage` into `navrules[postgres]`

**Date**: 2026-08-09
**Author**: Jesus Lara (investigation by Claude)
**Status**: exploration
**Recommended Option**: Option A (defer), revisit on a second consumer

---

## Problem Statement

The SaaS coupon engine is `navrules`' **first consumer in this repository** — a
whole-repo search for `navrules` outside its own package returns only two hits,
both in the root `pyproject.toml`. It needs rules stored per tenant in
Postgres, and `navrules.storages` ships only `FileStorage` and `MemoryStorage`.

The Community Manager phase put `PostgresRuleStorage` in the consumer
(`parrot_saas/rules/storage.py`). This document records why, and the condition
under which that decision should be revisited — so the choice is a decision
with an expiry rather than an accident.

## Why it is not upstream today

`navrules` declares `dependencies = []`. That is not incidental: the README
leads with *"Zero mandatory dependencies — stdlib only; pandas and cel are
extras."* Its `storages/file.py` uses only `asyncio`, `json` and `pathlib`, and
`AbstractStorage`'s own docstring names itself "the extension point for
DB-backed definitions" — i.e. the absence of a DB backend is the design, not an
omission.

Adding `asyncdb` upstream would turn a pure, Rust-accelerated rules library
into one coupled to a database for every future consumer, including consumers
that only ever load rules from a JSON file.

## What the consumer implementation actually needs

The port is small — `AbstractStorage` is an async context manager with a single
`async load() -> list[dict]`, and storages yield **plain spec dicts** that
`RuleLoader.load` resolves by `rule_type`. So the whole backend is one query
plus row-to-dict mapping.

Two constraints discovered while writing it are worth carrying upstream in any
case, because they are easy to get wrong and are not obvious from the README:

1. **`Policy.FIRST_MATCH` is effectively mandatory for payload-returning
   rulesets.** `_evaluate_sync_python` sets `value = self.default` for
   `ALL_MATCH`/`ANY_MATCH` and only emits per-rule `matched`/`rule`; the
   matching rule's `result` payload is returned only under FIRST_MATCH. The
   native sync and batch paths support FIRST_MATCH only.
2. **Priority ties resolve by insertion order.** `compile()` sorts with a
   *stable* sort on `-priority`, so equal priorities keep whatever order the
   storage returned. A SQL storage must therefore add a deterministic secondary
   `ORDER BY` (the consumer uses `rule_id`) or rule precedence silently varies
   between queries.

Also relevant to any tenant-editable rule store: `evaluate_sync()` raises
`RuntimeError` if *any* rule is non-declarative, so a write API must reject
`rule_type` values other than `ConditionRule` at write time rather than
discovering it at evaluation time.

---

## Options Explored

### Option A: Keep it in the consumer (status quo) — RECOMMENDED for now

✅ **Pros:** preserves the zero-dependency guarantee; the consumer is free to
use whatever DB layer it already has (`asyncdb`); no upstream release needed.

❌ **Cons:** a second consumer will copy it; the two constraints above stay
tribal knowledge unless documented upstream.

📊 **Effort:** None.

### Option B: `navrules[postgres]` optional extra

Ship `navrules/storages/postgres.py` behind an extra, with `asyncpg` (not
`asyncdb` — that would import a much larger stack into a library that prides
itself on having none).

✅ **Pros:** one implementation; the FIRST_MATCH and tie-break constraints get
documented where consumers read them.

❌ **Cons:** the extra still has to be maintained and tested; a table schema in
a generic library is a guess about the consumer's schema, and the SaaS one is
tenant-scoped in a way another consumer may not want.

📊 **Effort:** Low-Medium.

**Trigger to adopt:** a second in-repo consumer, or an external consumer asking
for it. Not before — a shared abstraction derived from one example usually
encodes that example's incidental choices.

### Option C: Generic `SqlStorage` taking a query

Upstream a storage that takes a DSN and a caller-supplied SQL string.

✅ **Pros:** no schema assumption.
❌ **Cons:** the caller still writes the SQL, so it saves almost nothing over
implementing `AbstractStorage` directly — which is already a ~30-line class.
📊 **Effort:** Low, low value.

---

## Recommendation

Option A, with two follow-ups that are worth doing regardless of where the
storage lives:

1. Document the FIRST_MATCH payload constraint and the stable-sort tie-break in
   the `navrules` README. Both are behavioural contracts a consumer must know,
   and neither is currently stated.
2. Revisit Option B when a second consumer appears.

## Open Questions

- [ ] Should `RuleSet` warn (or raise) when constructed with `ALL_MATCH`/
      `ANY_MATCH` *and* rules that carry a `result` payload? That combination
      is almost certainly a mistake, and today it silently returns the default.
- [ ] Is a `navrules` rule-authoring/validation helper worth extracting from the
      SaaS rules API, so any consumer can validate a spec dict before storing it?
