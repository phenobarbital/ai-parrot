# TASK-4240: Judge models (Rubric / JudgeVerdict / cache key) and JudgeCache backends

**Feature**: FEAT-652 — Answer-Accuracy Metrics for the Evaluation Harness
**Spec**: `sdd/specs/eval-answer-accuracy-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. FEAT-217 decided the LLM-as-judge design (D4) and created the `judge_cache`
table in `PostgresEvalSink._SCHEMA_DDL` but never used it. This task adds the data models the
judge needs, a deterministic cache key, and two cache backends (in-memory, Postgres). The
metric that calls the LLM is TASK-4241; this task is LLM-free.

---

## Scope

- Create `eval/judge/__init__.py`, `eval/judge/models.py` (`JudgeCriterion`, `Rubric`,
  `JudgeVerdict`, `judge_cache_key`), `eval/judge/cache.py` (`JudgeCache`, `InMemoryJudgeCache`,
  `PostgresJudgeCache`).
- Unit tests; Postgres test gated on `EVAL_DB_DSN` exactly like `test_postgres_sink.py`.

**NOT in scope**: the LLM call / prompt (TASK-4241); DDL changes (table already exists); exports in `eval/__init__.py` (TASK-4243).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/judge/__init__.py` | CREATE | re-exports |
| `packages/ai-parrot/src/parrot/eval/judge/models.py` | CREATE | rubric/verdict models + cache key |
| `packages/ai-parrot/src/parrot/eval/judge/cache.py` | CREATE | cache ABC + backends |
| `packages/ai-parrot/tests/eval/test_judge_cache.py` | CREATE | key stability + backends |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.sink import PostgresEvalSink, _SCHEMA_DDL   # verified: eval/sink.py:100, :60 (module-level str)
from pydantic import BaseModel, Field                        # pydantic v2 (project-wide)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/eval/sink.py
_SCHEMA_DDL = """ ... CREATE TABLE IF NOT EXISTS judge_cache (
    id BIGSERIAL PRIMARY KEY, cache_key TEXT NOT NULL UNIQUE, judge_model_version TEXT NOT NULL DEFAULT '',
    rubric_version TEXT NOT NULL DEFAULT '', verdict JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()); """   # lines 89-97
class PostgresEvalSink(EvalReportSink):                      # line 100
    def __init__(self, dsn: str | None = None) -> None       # line 117 — self._dsn = dsn or self._resolve_dsn()
    @staticmethod
    def _resolve_dsn() -> str | None                         # line 122 — navconfig config("EVAL_DB_DSN", default=None), None on any error
    # connection pattern (line 177-185): `import asyncpg` lazily; `conn = await asyncpg.connect(self._dsn)`; try: await conn.execute(_SCHEMA_DDL) ... finally: await conn.close()

# packages/ai-parrot/tests/eval/test_postgres_sink.py:12-19 — `_get_dsn()` helper; DB tests `pytest.mark.skipif(not _get_dsn(), ...)`
```

### Does NOT Exist
- ~~`parrot.eval.judge`~~ — created here.
- ~~`PostgresEvalSink.get_connection()`~~ / ~~connection pool~~ — the sink opens one `asyncpg.connect` per call; do the same.
- ~~`judge_cache.expires_at`~~ — no TTL column; do not add one.
- ~~`Rubric.prompt_template`~~ — spec §8 leaves it for later; do not add now.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/eval/judge/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/eval/judge/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/eval/judge/cache.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/eval/test_judge_cache.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/eval/sink.py#PostgresEvalSink",
    "sym:packages/ai-parrot/src/parrot/eval/sink.py#_SCHEMA_DDL"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Cache key = `sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str))` over
  `{"judge_model", "rubric_name", "rubric_version", "criteria": [[name, question], ...], "question", "expected", "answer"}`.
  Never include the judge's own output, timestamps or sample count.
- `PostgresJudgeCache.set` is an UPSERT: `INSERT ... ON CONFLICT (cache_key) DO UPDATE SET verdict = EXCLUDED.verdict, judge_model_version = EXCLUDED.judge_model_version, rubric_version = EXCLUDED.rubric_version`.
- `get` returns `JudgeVerdict.model_validate(row["verdict"])` (asyncpg returns JSONB as `str` unless a codec is set → `json.loads` when it is a `str`).
- No DSN → `RuntimeError` with the same message style as the sink.

### References in Codebase
- `packages/ai-parrot/src/parrot/eval/sink.py:142-215` — asyncpg usage pattern to mirror.

---

## Implementation Blueprint

### Steps (in order)
1. Write `models.py` — *why*: TASK-4241 imports these names; they are fixed by the spec skeleton.
2. Write `cache.py` with the ABC and the in-memory backend first, then Postgres — *why*: the in-memory backend is what every hermetic test uses.
3. Write `__init__.py` re-exports and the tests.

### `packages/ai-parrot/src/parrot/eval/judge/models.py` (CREATE)
```python
"""Rubric / verdict models and the deterministic judge cache key (FEAT-652, Module 4)."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field


class JudgeCriterion(BaseModel):
    """One yes/no question the judge answers about an answer."""

    name: str
    question: str


class Rubric(BaseModel):
    """Versioned list of criteria; ``pass_threshold`` is the fraction that must be True."""

    name: str
    version: str
    criteria: list[JudgeCriterion] = Field(min_length=1)
    pass_threshold: float = Field(default=1.0, ge=0.0, le=1.0)


class JudgeVerdict(BaseModel):
    """Per-criterion booleans plus a short rationale."""

    criteria: dict[str, bool]
    rationale: str = ""


def judge_cache_key(*, judge_model: str, rubric: Rubric, question: str, expected: Any, answer: str) -> str:
    """sha256 hex of the canonical JSON of everything that determines a verdict (never the verdict itself)."""
    payload = {
        "judge_model": judge_model,
        "rubric_name": rubric.name,
        "rubric_version": rubric.version,
        "criteria": [[c.name, c.question] for c in rubric.criteria],
        "question": question,
        "expected": expected,
        "answer": answer,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
```
**Why**: the key covers rubric name+version+criteria text so editing a rubric invalidates old
verdicts (spec §7), and `default=str` keeps arbitrary `expected` payloads hashable.

### `packages/ai-parrot/src/parrot/eval/judge/cache.py` (CREATE)
```python
"""JudgeCache backends (FEAT-652, Module 4)."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

from parrot.eval.judge.models import JudgeVerdict
from parrot.eval.sink import PostgresEvalSink, _SCHEMA_DDL

logger = logging.getLogger(__name__)


class JudgeCache(ABC):
    """Async key → verdict store."""

    @abstractmethod
    async def get(self, key: str) -> JudgeVerdict | None: ...

    @abstractmethod
    async def set(self, key: str, verdict: JudgeVerdict, *, judge_model_version: str, rubric_version: str) -> None: ...


class InMemoryJudgeCache(JudgeCache):
    """Dict-backed cache for tests and local runs."""

    def __init__(self) -> None:
        self._store: dict[str, JudgeVerdict] = {}

    async def get(self, key: str) -> JudgeVerdict | None:
        return self._store.get(key)

    async def set(self, key: str, verdict: JudgeVerdict, *, judge_model_version: str, rubric_version: str) -> None:
        self._store[key] = verdict


class PostgresJudgeCache(JudgeCache):
    """asyncpg-backed cache over the ``judge_cache`` table created by ``PostgresEvalSink._SCHEMA_DDL``."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or PostgresEvalSink._resolve_dsn()
        self.logger = logging.getLogger(__name__)

    def _require_dsn(self) -> str:
        if not self._dsn:
            raise RuntimeError("PostgresJudgeCache: no DSN configured. Set EVAL_DB_DSN or pass dsn=.")
        return self._dsn

    async def get(self, key: str) -> JudgeVerdict | None:
        import asyncpg  # lazy, optional dependency (same as PostgresEvalSink)
        conn = await asyncpg.connect(self._require_dsn())
        try:
            await conn.execute(_SCHEMA_DDL)
            row = await conn.fetchrow("SELECT verdict FROM judge_cache WHERE cache_key = $1", key)
        finally:
            await conn.close()
        # FILL IN: None when no row; json.loads when row["verdict"] is a str; JudgeVerdict.model_validate — bounded by AC-3
        raise NotImplementedError

    async def set(self, key: str, verdict: JudgeVerdict, *, judge_model_version: str, rubric_version: str) -> None:
        # FILL IN: connect, ensure schema, UPSERT per Implementation Notes with $1..$4 and ::jsonb cast, close in finally — bounded by AC-3
        raise NotImplementedError
```
**Why**: the Postgres backend copies the sink's connection discipline (lazy import, one
connection per call, idempotent DDL) so no new infrastructure or pooling decision is introduced.

### `packages/ai-parrot/src/parrot/eval/judge/__init__.py` (CREATE)
```python
"""LLM-judge support: rubric models, cache key and cache backends (FEAT-652)."""
from parrot.eval.judge.cache import InMemoryJudgeCache, JudgeCache, PostgresJudgeCache
from parrot.eval.judge.models import JudgeCriterion, JudgeVerdict, Rubric, judge_cache_key

__all__ = ["JudgeCache", "InMemoryJudgeCache", "PostgresJudgeCache", "JudgeCriterion", "JudgeVerdict", "Rubric", "judge_cache_key"]
```

### `packages/ai-parrot/tests/eval/test_judge_cache.py` (CREATE)
```python
"""Unit tests for judge models and caches (TASK-4240)."""
import os
import pytest
from parrot.eval.judge import InMemoryJudgeCache, JudgeCriterion, JudgeVerdict, PostgresJudgeCache, Rubric, judge_cache_key


def _rubric(version="1"):
    return Rubric(name="qa", version=version, criteria=[JudgeCriterion(name="correct", question="Is it correct?")])


def test_cache_key_stable_and_sensitive():
    k1 = judge_cache_key(judge_model="j", rubric=_rubric(), question="q", expected={"answer": "a"}, answer="a")
    # FILL IN: same inputs → same key; version "2" or judge_model "j2" or answer "b" → different key; len == 64 — bounded by AC-1

# FILL IN: test_inmemory_roundtrip; test_postgres_requires_dsn (dsn=None, env unset → RuntimeError on get);
#          @pytest.mark.skipif(not os.environ.get("EVAL_DB_DSN"), reason="EVAL_DB_DSN not set") test_postgres_upsert — bounded by AC-2, AC-3
```

### FILL IN checklist
- [ ] `cache.py::PostgresJudgeCache.get/set` — row decoding and UPSERT; AC-3
- [ ] `test_judge_cache.py` — four tests; AC-1..AC-3

---

## Acceptance Criteria

- [ ] AC-1: `judge_cache_key` is stable for equal inputs and changes with rubric version, criteria text, judge model, question, expected or answer.
- [ ] AC-2: `InMemoryJudgeCache` round-trips; `PostgresJudgeCache(dsn=None)` with no `EVAL_DB_DSN` raises `RuntimeError` on use (never at construction).
- [ ] AC-3: with `EVAL_DB_DSN`, `set` twice on one key leaves one row (UPSERT) and `get` returns the latest verdict; test skipped otherwise.
- [ ] `from parrot.eval.judge import Rubric, JudgeVerdict, JudgeCache, InMemoryJudgeCache, PostgresJudgeCache, judge_cache_key` resolves.
- [ ] `ruff check packages/ai-parrot/src/parrot/eval/judge/` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/eval/test_judge_cache.py -q`
- `pytest packages/ai-parrot/tests/eval/test_postgres_sink.py -q`

---

## Test Specification

See the blueprint block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug eval-answer-accuracy-metrics --feature-id FEAT-652`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — `grep`/`read` every reference before writing code
5. **Update status** in `sdd/tasks/index/eval-answer-accuracy-metrics.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:`; never change a signature or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the four files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4240 eval-answer-accuracy-metrics verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4240
- Feature: eval-answer-accuracy-metrics
- Implementation SHA: a30b942983d9d41fc3b6b3a09f3d274cd57242ba
- Closed at (UTC): 2026-10-12T17:18:04+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: 113s · Tokens: n/a |
