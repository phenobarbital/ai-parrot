# FC-007 — One OPEN ledger issue against the semantic layer: three behaviours (S3, S5, nits) a new example must not present as correct

**Query**: Q014 · **Type**: grep+ledger · **Depth**: 0

## Summary
`ledger list --about-prefix sym:packages/ai-parrot-semantic --statuses open,claimed` returns exactly
one issue: `issue:3c4d154c0172` — *"semantic toolkit: catalog/minor hardening follow-ups from
FEAT-704 review"* (tech_debt / minor / open, unclaimed, `discovered_from: spec:FEAT-704`). Its
unclaim note (2026-10-20) records that **S1, S2 and S4 are fixed**, and that three items remain
genuinely open:
- **S3** — `toolkit.py::_pre_execute` falls back to `static_subject` whenever `_permission_context`
  is missing; it should only do that on the `mcp-local` channel. ⇒ an MCP-local example must not be
  written as if the static-subject fallback were channel-scoped today.
- **S5** — `save_result_as_dataset` re-checks only that *some* member is visible, not the handle's
  own members. ⇒ do not narrate `sl_save_result_as_dataset` as a per-member re-authorization.
- **Nits** — `trusted_nodes` relies on `id()` of nodes; `LoadedModel.schema` shadows a pydantic
  `BaseModel` attribute (emits a warning on every run); redundant `expires_at=now()` at
  `toolkit.py:285/483`; `handlers/semantic.py:201` `logger.exception` outside an `except` (ruff LOG004 —
  LOG *is* in this repo's ruff `select`).

Every other semantic-layer ledger entry is **closed**. Note the unclaim note's warning that the code
"exists ONLY on the unmerged FEAT-704 branch" — that is now **stale**: `packages/ai-parrot-semantic/`
is on `dev` and CI runs its tests.

## Citations
- `sdd/ledger/issues.jsonl:110` — `issue:3c4d154c0172`, `status: "open"`, `kind: "tech_debt"`, `severity: "minor"`, about `toolkit.py#SemanticLayerToolkit`, `engines/__init__.py#compile`, `governance/pbac.py#PbacGate`
- `wikitoolkit ledger show issue:3c4d154c0172` → event `cce538c604a3` (`issue.unclaimed`, `agent:sdd-fix`, 2026-10-20T23:46:43Z) — the S1/S2/S4-done, S3/S5/nits-open breakdown quoted above
- `sdd/ledger/issues.jsonl:484` — `issue:f0da823294fb` (closed, major) *"semantic example: PBAC bypass via private attr, env leak, weak facade owner check, coverage gaps"* — the review that forced the current example's `DataPlanePolicyGuard`, `connection_env()`, owner pre-check and failing-denial demo. **A new example that re-introduces any of those four is a known regression.**
- `sdd/ledger/issues.jsonl:65` — `issue:22fbd14d96a9` (closed, vulnerability) — `compiled_sql`/`compile_query` now return **pre-RLS** SQL; governed SQL lives only in the audit record. An example that prints `compile_query` output must not call it "the SQL as executed".
- `sdd/ledger/issues.jsonl:299` — `issue:9a4e4c35b032` (closed) — usage rights restrict **only** masked columns / `sensitive: true` members; a granted metric needs no `usage:` grant for its aggregate input. The current example's `usage: [sales.orders.region, sales.orders.amount]` is therefore broader than necessary and should not be copied as "required".
- `sdd/ledger/issues.jsonl:368` — `issue:bd477252b8f3` (closed) — a policy model covers only its own table, relationship-reachable tables, and tables its own masks/rls name. A multi-model example must declare the relationship or qualification fails.
- `sdd/ledger/issues.jsonl:451` — `issue:e3ff9bfb4a83` (closed) — `RlsRegistry` has **no unregister API**: removed policy RLS rules stay in force after a `reload()` (fail-safe, warns). An example must not show `reload()` as a way to drop an RLS rule.

## Notes
- `[cross-lane: type=risk, intent=the open issue is minor/unclaimed; the proposal should state that the new examples neither fix nor depend on S3/S5]`
