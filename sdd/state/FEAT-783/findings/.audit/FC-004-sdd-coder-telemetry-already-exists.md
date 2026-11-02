---
id: FC-004
query_id: Q015
type: read
intent: "Read sdd_coder/telemetry.py in full - confirm or refute that a telemetry sink already exists."
executed_at: 2026-10-30T22:41:00Z
duration_ms: 600
parent_id: null
depth: 0
---

# FC-004 — REFUTED: durable per-attempt token telemetry already exists (FEAT-554) and already carries the source's correlation key

## Summary

The source document's framing — "the only seat whose usage lands in SDD state, via
`coder_begin_execution`/`coder_end_execution`" and "no store owns per-spec numbers" — is
**substantially out of date**. `flows/dev_loop/sdd_coder/telemetry.py` (311 lines, FEAT-554)
is a complete, shipped, append-only per-attempt usage dataset. `AttemptUsageRow`
(telemetry.py:40-75) already carries **every field the source proposes as the correlation
key**: `feature_id`, `task_id`, `attempt_uid`, `execution_id`, `seat_label`, `backend`,
`configured_model`, `resolved_model`, plus `job_id` and `attempt`. It carries
`provider_input_tokens`/`provider_output_tokens` (provider-reported) **side by side with**
seven `ledger_*` counters projected from a `BudgetReport`, a `turn_series` of
per-round `(round, input, output)` tuples, and a `calibration_eligible` flag whose rule
("ledger accounting complete AND no turn reported unknown usage") is documented as living
in exactly one place. The sink writes one JSONL file per feature under a root that is
deliberately resolved to the **main checkout** via `git rev-parse --git-common-dir` and is
**refused if it resolves inside the worktree base**, so the dataset outlives
`git worktree remove` — the same shared-root problem the source credits only to the ledger.

What is genuinely missing is narrower than the source assumes: **no cache-token counters,
no cost/USD field anywhere, no per-request granularity (rows are per attempt), and no
reader** — see FC-005.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 1-8
  symbol: `module docstring`
  excerpt: |
    """Durable per-attempt token telemetry for sdd-coder (FEAT-554).

    Two append-only JSONL line kinds per attempt, joined on `attempt_uid`:
    an `attempt` row written when the attempt returns, and one or more `outcome`
    rows written as the attempt's fate is decided. Rows carry counters, ids and
    timings ONLY — never prompt text, tool arguments or exception messages
    (spec §10 R5).
    """

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 44-56
  symbol: `AttemptUsageRow`
  excerpt: |
    ts: str
    attempt_uid: str = Field(..., min_length=8, max_length=64)
    job_id: str = Field("", max_length=64)
    feature_id: str = Field(..., max_length=64)
    task_id: str = Field(..., max_length=64)
    attempt: int = Field(..., ge=1, le=3)
    seat_label: str = Field("", max_length=32)
    backend: str = Field("", max_length=32)
    configured_model: str = Field("", max_length=200)
    resolved_model: str = Field("", max_length=200)

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 60-75
  symbol: `AttemptUsageRow`
  excerpt: |
    provider_input_tokens: Optional[int] = None
    provider_output_tokens: Optional[int] = None
    ledger_input_tokens: Optional[int] = None
    ledger_output_tokens: Optional[int] = None
    ledger_settled_estimate_input_tokens: Optional[int] = None
    ledger_released_estimate_tokens: Optional[int] = None
    ledger_uncertain_tokens: Optional[int] = None
    ledger_overrun_tokens: Optional[int] = None
    turn_series: List[Tuple[int, Optional[int], Optional[int]]] = Field(default_factory=list)
    execution_id: str = Field("", max_length=64)

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 107-116
  symbol: `resolve_durable_root`
  excerpt: |
    def resolve_durable_root(configured: Optional[str], *, worktree_base_path: str) -> Path:
        """Resolve and validate the telemetry root, or raise ValueError.

        An explicit absolute *configured* path wins. Otherwise the main checkout is
        derived from `git rev-parse --path-format=absolute --git-common-dir`, which
        points at the MAIN repository's `.git` even when called inside a linked
        worktree. A root that resolves under *worktree_base_path* is REFUSED: the
        dataset must outlive `git worktree remove` ...
        """

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 145-148
  symbol: `resolve_durable_root`
  excerpt: |
    # git_common_dir is usually /path/to/main/.git; its parent is the main checkout root.
    main_checkout = Path(res.stdout.strip()).resolve().parent
    resolved = (main_checkout / "artifacts" / "logs" / "sdd-coder-usage").resolve()
    break

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 233-234
  symbol: `build_attempt_row`
  excerpt: |
    provider_input_tokens=record.usage.get("input_tokens") if isinstance(record.usage, dict) else None,
    provider_output_tokens=record.usage.get("output_tokens") if isinstance(record.usage, dict) else None,

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 176-178
  symbol: `build_attempt_row`
  excerpt: |
    Sets `calibration_eligible` = ledger accounting complete AND no turn
    reported unknown usage — the one place that rule lives.

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 268-275
  symbol: `CoderTelemetrySink._append`
  excerpt: |
    """Serialize-check then ONE os.write to an O_APPEND fd, off the loop.

    Runs the blocking write through `asyncio.to_thread`, the pattern
    `_journal` follows (verified: engine.py:472-488). Every failure is
    logged once at WARNING and dropped: a telemetry problem must never
    change a dispatch or a merge outcome (AC-11).
    """

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 294-302
  symbol: `CoderTelemetrySink._append._write`
  excerpt: |
    def _write() -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        fd = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
  lines: 129-133
  symbol: `engine imports`
  excerpt: |
    from parrot.flows.dev_loop.sdd_coder.telemetry import (
        CoderTelemetrySink,
        build_attempt_row,
        resolve_durable_root,
    )

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
  lines: 291-300
  symbol: `on_attempt_telemetry`
  excerpt: |
    def on_attempt_telemetry(self, telemetry: AttemptTelemetry) -> None:
        """Receive the dispatcher's terminal telemetry (FEAT-554, spec §10 R3).

        Called by `LLMCodeDispatcher._emit_attempt_telemetry` through the bound
        ...
        self.telemetry = telemetry

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`
  lines: 111
  symbol: `telemetry_dir`
  excerpt: |
    telemetry_dir: Optional[str] = None,

## Notes

- `MAX_LINE_BYTES = 8192` with a documented worst case of ~3.6 KB (telemetry.py:25-35), and a
  path-traversal guard on `feature_id` before the filename join (`feature_file_name`,
  telemetry.py:96-104) — this component is hardened, not a prototype.
- The sink **never raises** and warns once (telemetry.py:308-311): a usage pipeline built here
  inherits a fail-open posture, which is the right default for telemetry but means missing
  rows are silent. Any "correct per-spec cost" claim must reckon with that.
- The source's `usage.priced` / price-table design has no counterpart here: grep over all 1090
  attempt rows finds **no field containing `cache`, `cost` or `usd`** (FC-005).
- [cross-lane: type=git_log, intent=when did FEAT-554 land and has the row schema changed since?]
