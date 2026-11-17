---
id: F017
query_id: Q032
type: read
intent: "Read the sdd_coder roster to see the seat/model vocabulary the usage plane must key on (seat, backend, model)."
executed_at: 2026-10-30T23:11:00Z
duration_ms: 350
parent_id: null
depth: 0
lane: codebase
merged_from: ['FC-017']
---

# F017 — "Seat" already has two incompatible meanings in this codebase, and the MCP toolkit already exposes the execution boundary

## Summary

The source uses `seat` as a three-valued dimension (`dev-loop` / `Claude Code native` /
`Codex`). The codebase uses the word twice, differently, and neither matches:

1. **sdd-coder roster seat** — a `label` (`"a"`, `"b"`, `"c"` in the real data, FC-005) plus
   a `kind` (`"native"` or a backend) and a `backend` (`nova`, `google-compat`, `codex`, …).
   Availability is probed by `_KEY_RULES` (env-var-backed backends) or `_CLI_RULES`
   (`{"codex": "codex", "google_coding": "agy"}` — binary-backed backends).
2. **observability seat** — a free string naming the accounting node, e.g. `"development"`
   or the pool-worker seat `"development.w1"`, which rolls up to a `node_id` (FC-007,
   `run_ledger.py:11-14`).

So a usage plane keyed on "seat" must pick one of three vocabularies and map the other two.
The source's `seat` is closest to the *dispatch mechanism* (in-process vs CLI), which is
exactly what `kind` + `_CLI_RULES` already encodes.

On the toolkit side, the MCP surface is wider than the source lists: 20 `coder_*` tools
including `coder_begin_execution(feature, worktree, execution_id)` and
`coder_end_execution(execution_id)`, plus `coder_run_validation`, `coder_bg_status`,
`coder_bg_wait`, `coder_delivery_report`, `coder_task_context` and `coder_read_artifact`.
**Every per-task tool already takes `execution_id` as a required argument**, so the
correlation key the source wants to introduce is already threaded through the whole MCP
boundary.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py`
  lines: 20-24
  symbol: `backend availability rules`
  excerpt: |
    _KEY_RULES: Dict[str, tuple[str, ...]] = {
    ...
    _CLI_RULES: Dict[str, str] = {"codex": "codex", "google_coding": "agy"}

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py`
  lines: 76-98
  symbol: `RosterProbe.probe`
  excerpt: |
    if seat.kind == "native":
        return SeatProbeResult(label=seat.label, kind="native", available=True, model_used=model)
    backend = seat.backend or ""
    if backend in _KEY_RULES:
        keys = _KEY_RULES[backend]
    elif backend in _CLI_RULES:
        binary = _CLI_RULES[backend]

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`
  lines: 423-438
  symbol: `execution boundary tools`
  excerpt: |
    async def coder_begin_execution(self, feature: str, worktree: str, execution_id: str) -> CoderResult:
    ...
    async def coder_end_execution(self, execution_id: str) -> CoderResult:

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`
  lines: 304-320
  symbol: `per-task tools carry execution_id`
  excerpt: |
    async def coder_run_chunk(self, feature: str, worktree: str, task_ids: List[str], execution_id: str) -> CoderResult:
    async def coder_prepare_native(self, feature: str, worktree: str, task_id: str, execution_id: str) -> CoderResult:
    async def coder_merge(self, feature: str, worktree: str, task_id: str, execution_id: str) -> CoderResult:

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`
  lines: 389-416
  symbol: `report tools`
  excerpt: |
    async def coder_task_context(self, feature: str, worktree: str, task_id: str, execution_id: str) -> CoderResult:
    async def coder_delivery_report(self, feature: str, worktree: str, task_id: str, execution_id: str) -> CoderResult:
    async def coder_feedback_report(self, feature: str, worktree: str) -> CoderResult:

- path: `packages/ai-parrot/src/parrot/observability/recorders/run_ledger.py`
  lines: 11-14
  symbol: `the other meaning of "seat"`
  excerpt: |
    seat is a free string (FEAT-479 Module 2), a pool-worker seat like
    ``"development.w1"`` is a first-class row here

## Notes

- `coder_delivery_report` and `coder_feedback_report` show the established shape for a
  read-side report tool, i.e. `coder_usage_report(execution_id)` would be the fifth tool of
  its kind rather than a new pattern.
- 29 ledger test modules exist across `packages/ai-parrot/tests/knowledge/wiki/` and
  `tests/knowledge/wiki/` (two trees — both must be updated for any ledger change).
- `packages/ai-parrot/src/parrot/mcp/` holds `local_cli.py`, `local_server.py`,
  `agent_tools.py`, `adapter.py`, `hosts.py`, `filtering.py`, `integration.py`, `context.py`,
  `client.py`; a grep for `ledger_*` in `local_cli.py` returned nothing, so the wikitoolkit
  MCP `ledger_*` tools the source references are registered elsewhere, not in that file.
