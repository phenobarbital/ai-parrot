---
id: F013
query_id: Q013
type: read
intent: Is `filter: {graduation_details: {"@>": [...]}}` supported, and in which querysource version
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F013 — JSONB `@>` filter is supported only since querysource 5.1.0; the shared venv has 5.0.0
## Summary
In querysource ≥5.1.0 the PostgreSQL parser renders a dict-typed filter value as a JSONB condition: `{"col": {"@>": operand}}` → `col @> '<json>'::jsonb` (operand dict/list/scalar or JSON text), `{"<@": ...}`, `{"@>|": [a,b]}` (OR-ed any-of), `->`/`->>` key comparisons, and an operator-less dict as implicit containment. Filter keys must be plain identifiers (alnum/`_`/`.`) — expressions like `jsonb_array_length(x)` are silently skipped. This was added by querysource commit `4d7cccc` ("fix(pgsql): render JSONB filter conditions ... correctly", first tag 5.1.0), whose message states dict filters "never produced valid SQL" before. The ai-parrot `.venv` has **querysource 5.0.0** installed, whose compiled parsers contain none of `jsonb_condition`/`JSONB_OPERATORS`/`pg_literal`; `ai-parrot-tools[db]` already declares `querysource>=5.1.1`, core `ai-parrot` only `>=4.1.11`.
## Citations
- path: `../querysource/querysource/parsers/pgsql.pyx`
  lines: 27-29
  symbol: `JSONB_OPERATORS`
  excerpt: |
    # JSONB operators accepted as the key of a dict-typed filter value.
    # ``@>|`` is the any-of form: a list of containment operands OR-ed together.
    JSONB_OPERATORS = ('@>', '<@', '@>|', '->', '->>',)
- path: `../querysource/querysource/parsers/pgsql.pyx`
  lines: 186-193
  symbol: `jsonb_condition`
  excerpt: |
    if operators == 0:
        return (True, f"{col} @> {pg_literal(jsonb_dumps(value))}::jsonb")
    if operators != len(value):
        return (True, None)
    if op in ('@>', '<@'):
        return (True, f"{col} {op} {pg_literal(jsonb_operand(operand))}::jsonb")
    if op == '@>|':
        return (True, jsonb_any_of_condition(col, operand))
- path: `../querysource/querysource/parsers/pgsql.pyx`
  lines: 238-243
  symbol: `pgSQLParser._filter_conditions_cy`
  excerpt: |
    stripped = key.rstrip('|!~#@:')
    if not all(c.isalnum() or c == '_' or c == '.' for c in stripped):
        continue
- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 77
  symbol: `-`
  excerpt: |
    db = ["querysource>=5.1.1", "psycopg-binary>=3.2"]
- path: `venv:querysource-5.0.0.dist-info/METADATA`
  lines: 3
  symbol: `-`
  excerpt: |
    Version: 5.0.0
## Implications
- The spec's `{"graduation_details": {"@>": [{"course": "Pilates Studio"}]}}` is valid syntax for ≥5.1.0 and renders `graduation_details @> E'[\x7b"course": "Pilates Studio"\x7d]'::jsonb`.
- The example must pin/require `querysource>=5.1.1` (e.g. via `ai-parrot-tools[db]`) and the shared venv must be upgraded before any E2E run; otherwise the two Pilates KPIs fail. Do not `uv sync` inside a worktree (memory: shared venv hazard).
- Git evidence: `git -C ../querysource log -S JSONB_OPERATORS` → `4d7cccc`; `git tag --contains 4d7cccc` → `5.1.0`.
