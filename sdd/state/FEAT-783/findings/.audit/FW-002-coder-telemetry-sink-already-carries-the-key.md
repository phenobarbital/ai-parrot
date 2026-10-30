---
id: FW-002
query_id: Q003
type: wiki_query
intent: "Orient: sdd_coder/telemetry.py - an existing telemetry surface the brainstorm did not mention."
executed_at: 2026-10-30T22:38:36Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-002 — `CoderTelemetrySink` already writes per-feature usage rows carrying the EXACT correlation key the source proposes

## Summary

`flows/dev_loop/sdd_coder/telemetry.py` is an append-only JSONL usage sink the source does not
mention at all. Its `AttemptUsageRow` already carries `feature_id`, `task_id`, `attempt_uid`,
`execution_id`, `seat_label`, `backend`, `configured_model`/`resolved_model` — i.e. the source's
proposed key `(feat_id, task_id, attempt_uid, execution_id, seat, model)` minus nothing — plus
`provider_input_tokens` / `provider_output_tokens` AND a parallel set of `ledger_*` estimate
counters with `ledger_counting_methods` and `ledger_accounting_complete`. Files are written one
per feature (`<feature_id>.jsonl`) under a validated durable root.

So the dev-loop seat is not merely "the only seat whose usage lands in SDD state" — it already has
**full per-spec, per-attempt, per-seat token attribution on disk**. The real gaps are narrower:
no cache_read / cache_creation counters, no USD on the row, and the rows live in their own JSONL
root rather than in `events.jsonl` / `ledger.db`.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 40-75
  symbol: `AttemptUsageRow`
  excerpt: |
    class AttemptUsageRow(BaseModel):
        """The `attempt` JSONL line. See spec §2 Data Models for the field list."""
        kind: Literal["attempt"] = "attempt"
        ts: str
        attempt_uid: str = Field(..., min_length=8, max_length=64)
        job_id: str = Field("", max_length=64)
        feature_id: str = Field(..., max_length=64)
        task_id: str = Field(..., max_length=64)

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 52-56
  symbol: `AttemptUsageRow` (seat/model identity)
  excerpt: |
    seat_label: str = Field("", max_length=32)
    backend: str = Field("", max_length=32)
    configured_model: str = Field("", max_length=200)
    resolved_model: str = Field("", max_length=200)

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 61-72
  symbol: `AttemptUsageRow` (token counters)
  excerpt: |
    provider_input_tokens: Optional[int] = None
    provider_output_tokens: Optional[int] = None
    ledger_input_tokens: Optional[int] = None
    ledger_output_tokens: Optional[int] = None
    ledger_counting_methods: List[str] = Field(default_factory=list)
    ledger_accounting_complete: Optional[bool] = None
    turns_with_unknown_usage: int = 0

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 73-75
  symbol: `AttemptUsageRow.execution_id`
  excerpt: |
    execution_id: str = Field("", max_length=64)
    """FEAT-559: the execution this attempt ran under. Empty for historical records."""

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 251-311
  symbol: `CoderTelemetrySink`
  excerpt: |
    class CoderTelemetrySink:
        """One append-only JSONL file per feature under a validated root."""
        # write_attempt L260-262: "Append one `attempt` row. Never raises."
        # write_outcome L264-266: "Append one `outcome` row. Never raises."
        # _append    L268-311: "Serialize-check then ONE os.write to an O_APPEND fd, off the loop."

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 96-157
  symbol: `feature_file_name` / `resolve_durable_root`
  excerpt: |
    def feature_file_name(feature_id: str) -> str:   # "<feature_id>.jsonl", ValueError on unsafe id
    def resolve_durable_root(configured, *, worktree_base_path) -> Path

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 160-248
  symbol: `build_attempt_row`
  excerpt: |
    def build_attempt_row(record: AttemptRecord, *, feature_id, job_id, task_id, declared_files) -> AttemptUsageRow
    # "Project an AttemptRecord onto a row by EXPLICIT ALLOWLIST."

## Notes

The sink is gated: saved wiki memory `mem-d296bead08e8` states "SddCoderEngine binds its
ExecutionEvidenceStore ... unconditionally whenever a durable root resolves; `DEV_LOOP_CODER_TELEMETRY`
and `telemetry_dir` only gate the `CoderTelemetrySink` usage-row writer." So the usage rows are
**off by default** behind `DEV_LOOP_CODER_TELEMETRY`.

A FEAT-554 design-research artifact already states the remaining gap in this exact area:
"The current tree already contains lifecycle usage plumbing, but the proposed sdd-coder path does not
yet connect Google-compatible clients, failed-attempt usage, or estimate-vs-provider accounting."
(`sdd/state/FEAT-554/design_research/suggestions.json`, score=0.43) and its code-context file names
`artifacts/logs/sdd-coder-usage/` as the row destination.

[cross-lane: type=grep, intent=Find where DEV_LOOP_CODER_TELEMETRY is read and whether engine.py calls write_attempt on every attempt or only on success]
