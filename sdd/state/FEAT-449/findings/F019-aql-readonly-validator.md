---
id: F019
query_id: Q026
type: read
intent: Inspect AQL validation constraints that any custom legal traversal must satisfy
executed_at: 2026-08-23T00:41:45Z
depth: 2
parent_id: F011
---

# F019 — Read-only enforcement for graph queries already exists at the AQL layer

## Summary

`ontology/validators.py` enforces the source's §1.6 "read-only agents" invariant below the
tool layer: it rejects any AQL containing mutation keywords (`INSERT|UPDATE|REMOVE|REPLACE|
UPSERT`), any access to system collections (`_system|_graphs|_modules|_analyzers|_jobs|
_queues`), and any JavaScript execution (`APPLY|CALL|V8`), raising `AQLValidationError`. It is
explicitly scoped to "LLM-generated queries" from the intent resolver and also enforces depth
limits. A legal advisory agent therefore inherits a defence-in-depth read-only guarantee
without new code.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/validators.py`
  lines: 1-28
  excerpt: |
    """AQL security validation for LLM-generated queries.

    Ensures that dynamic AQL from the intent resolver is read-only,
    depth-limited, and does not access system collections or execute JavaScript.
    """
    _MUTATION_PATTERN = re.compile(
        r"\b(INSERT|UPDATE|REMOVE|REPLACE|UPSERT)\b",
    _SYSTEM_COLLECTIONS = re.compile(
        r"\b(_system|_graphs|_modules|_analyzers|_jobs|_queues)\b",
    _JS_PATTERN = re.compile(
        r"\b(APPLY|CALL|V8)\s*\(",

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py`
  symbol: `AQLValidationError`

## Notes

Complements F007: guardrails gate *which tools* may be called; this gates *what the query may
do*. Together they cover the source's §1.6 without the separate writer/reader toolkit split it
proposed.
