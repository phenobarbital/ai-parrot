# TASK-3092: Benchmark harness, baseline/optimized reports, documentation and release gate

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Estimated effort note**: harness + docs are M; running live-model scenarios is operator time outside this task.
**Depends-on**: TASK-3089, TASK-3090, TASK-3091
**Assigned-to**: unassigned

---

## Context

Spec §4 "Measurement Protocol", §3 Module M9 (docs + benchmarks), AC15,
§8 open question "Release scope and numeric success criteria" (the one
unresolved decision — numeric targets must NOT be fabricated). This
task delivers a reproducible harness that measures primary-model
tokens, delegate tokens, total cost, latency and correctness
**separately**, the user-facing documentation (deployment, coverage
matrix, limitations), and a release checklist that leaves the numeric
target as an explicit owner decision.

---

## Scope

- `benchmarks/tool_optimizations/` (new package; the existing
  `benchmarks/` directory already hosts `injection_guardrail_latency/`
  and `pageindex_embedding_latency/` — follow their layout):
  - `__init__.py`, `README.md` (how to run, what is measured, what is
    NOT claimed).
  - `scenarios.py`: `Scenario(BaseModel)` with `name`, `kind`
    (`git_fetch_preflight_prepare` | `targeted_read_large_file` |
    `decided_create_modify_task`), `repo_revision`, `inputs`, and the
    three fixed scenarios built from the FEAT-543 test fixtures
    (`make_repo_with_target`, `make_valid_task`, a generated 2,000-line
    file). Each scenario has a `baseline` recipe (the commands/reads a
    host would issue without the tools — e.g. the user's three shell
    lines from spec §6, a full-file `Read`, a hand-written
    implementation prompt) and an `optimized` recipe (the tool calls).
  - `accounting.py`: `UsageRecord(BaseModel)`: `stage`
    (`tool_schema_overhead` | `planning_packet` | `primary_input` |
    `primary_output` | `delegate_input` | `delegate_output` | `review` |
    `repair`), `tokens: int | None` (`None` = unknown, never 0 for
    missing), `source` (`provider_usage` | `estimate:<method>`),
    `elapsed_ms`; `CostModel(BaseModel)` loading
    `benchmarks/tool_optimizations/prices.yaml` (per-model USD per 1k
    input/output tokens with a `provenance` string + `as_of` date per
    row; ships with EMPTY prices and a comment — the operator fills real
    prices; `cost` is reported as `unknown` when a price is missing).
    Token estimation for the baseline side uses `len(text) // 4` and is
    labelled `estimate:chars_div_4`; provider usage (from
    `PatchManifest.usage`) is labelled `provider_usage`.
  - `runner.py`: `async run(scenario, mode, *, runs: int = 5, client_factory=None) -> RunReport`
    where `RunReport` has per-run `elapsed_ms`, usage records,
    `acceptance_passed: bool | None` (the real pytest exit code for
    task scenarios, `None` for read/git scenarios), `retries`,
    `warm: bool` (second+ run with the same client), model/config
    identity; `summarize(reports) -> Summary` with median and p95
    latency, token totals per stage, cost (or unknown), pass rate.
    Offline by default with the `FakeClient`; `--live` switches to
    `LLMFactory.create` from `examples/tool-optimizations-mcp.yaml` and
    is the only path that spends money.
  - `__main__.py`: `python -m benchmarks.tool_optimizations --scenario all --runs 5 [--live] --out artifacts/tool-optimizations/benchmarks/<timestamp>.json`
    plus a Markdown twin next to it; exit non-zero if any optimized
    scenario has `acceptance_passed is False` (correctness parity is
    mandatory; token/latency numbers are informational).
  - A pytest in `packages/ai-parrot-tools/tests/tool_optimizations/test_benchmark_harness.py`
    that runs the offline harness with `runs=1` for all three scenarios,
    checks the report schema, that unknown usage is `None`, that the
    primary-vs-total distinction is present ("never equate fewer primary
    tokens with fewer total tokens" → the Markdown must contain both
    columns), and that the Markdown lands under
    `artifacts/tool-optimizations/benchmarks/`.
- `docs/tool-optimizations.md` (new): sections — Overview & non-goals;
  Installation (`.parrot/mcp-toolkits.yaml` from `examples/tool-optimizations-mcp.yaml`,
  `parrot claude install --tool-guards`, `parrot codex install --tool-guards`,
  `parrot mcp-local --list`); Tool reference (every method, arguments,
  result fields, error codes — generate the error-code tables from the
  modules' constants to avoid drift); Git contract summary & refusal
  codes; Bounded reader contract (thresholds, continuation recipe with
  `next_line` + `expected_sha256`); Delegation workflow (packet grammar
  copied from TASK-3083/3090, generate → review → apply, recovery
  journal & `recovery_required` handling, `already_applied`); Client
  configuration (Bedrock/Qwen alias provenance, `fallback_model: null`
  requirement, `expected_model_ids`, credentials via the AWS chain, no
  secrets in config); Host guards — the **coverage matrix rendered from
  `hooks.coverage_matrix()`** (a test asserts the doc table matches the
  function output), documented bypasses (`sed -n`, heredocs, pipes into
  interpreters, Codex `write_stdin`, hosted tools), supported/tested
  host versions (from `artifacts/logs/host-versions.txt` at the time of
  writing: Claude Code 2.1.267, codex-cli 0.154.0) and the note that
  installed versions must be re-tested; Measurement protocol & how to
  run the benchmark; Limitations & security notes (filesystem
  non-atomicity, lock semantics, artifact permissions, data sent to the
  provider = approved slices only); Release checklist.
- `docs/mcp-local-toolkits.md`: add a "Related" link to the new page.
- Release gate text (in the docs "Release checklist" AND in the
  Completion Note): "Numeric token/cost/latency targets are an owner
  decision (spec §8). This feature ships with correctness parity
  enforced by the harness and reports the measured numbers; no
  percentage is claimed." Also list which spec ACs are covered by
  which test files (AC1–AC15 traceability table).

**NOT in scope**: choosing the numeric targets; running live-model
benchmarks (document the command; running them is an operator action
recorded in `artifacts/tool-optimizations/benchmarks/`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/tool_optimizations/__init__.py` | CREATE | Package |
| `benchmarks/tool_optimizations/README.md` | CREATE | Usage + caveats |
| `benchmarks/tool_optimizations/scenarios.py` | CREATE | Scenario definitions (baseline vs optimized recipes) |
| `benchmarks/tool_optimizations/accounting.py` | CREATE | Usage/cost models, `prices.yaml` loader |
| `benchmarks/tool_optimizations/prices.yaml` | CREATE | Empty price table with provenance fields |
| `benchmarks/tool_optimizations/runner.py` | CREATE | Runs, summary, report writers |
| `benchmarks/tool_optimizations/__main__.py` | CREATE | CLI entry |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_benchmark_harness.py` | CREATE | Offline harness test + doc/matrix sync test |
| `docs/tool-optimizations.md` | CREATE | User documentation |
| `docs/mcp-local-toolkits.md` | MODIFY | Related link |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.tool_optimizations.git import LocalGitToolkit
from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit
from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit
from parrot_tools.tool_optimizations.hooks import coverage_matrix                    # TASK-3088
from parrot_tools.tool_optimizations.models import PatchManifest, WriterLimits
from parrot.mcp.toolkit_config import load_toolkits_config                          # toolkit_config.py:80
# live mode only, imported lazily: from parrot.clients.factory import LLMFactory   # factory.py:257
import yaml   # already a core dependency (used by toolkit_config.py:15)
```

### Existing Signatures to Use
```text
benchmarks/                       existing dir: fixtures/, __init__.py, injection_guardrail_latency/, pageindex_embedding_latency/, multimodal_embedding_benchmark.py, requirements-benchmark.txt
artifacts/                        gitignored (.gitignore:283) → benchmark reports never enter git; the README says how to share them
docs/mcp-local-toolkits.md        :185 "## Related" — append the link there
root pyproject.toml:236           markers: asyncio, real_llm (use `real_llm` for anything that would spend tokens)
examples/tool-optimizations-mcp.yaml   (TASK-3087) — source of the live client configuration
packages/ai-parrot-tools/tests/tool_optimizations/fixtures.py   (TASK-3083) — make_repo_with_target / make_valid_task / GOOD_PATCH
packages/ai-parrot-tools/tests/tool_optimizations/test_writer.py (TASK-3085) — FakeClient
```

### Does NOT Exist
- ~~Any published token-saving percentage~~ — spec Non-Goals; the harness reports numbers, the docs claim none.
- ~~A price list in the repo~~ — `prices.yaml` ships empty with provenance fields; cost = `unknown` until filled.
- ~~`benchmarks` being importable from the installed package~~ — it is a repo-level directory (`benchmarks/__init__.py` exists); run with `python -m benchmarks.tool_optimizations` from the repo root with the venv active.
- ~~Baseline token counts from a provider~~ — baseline is an estimate and must be labelled as such.
- ~~Running live benchmarks in CI~~ — offline only; live runs are manual.

---

## Implementation Notes

### Pattern to Follow
```python
# accounting.py
class UsageRecord(BaseModel):
    stage: Literal["tool_schema_overhead", "planning_packet", "primary_input", "primary_output",
                   "delegate_input", "delegate_output", "review", "repair"]
    tokens: int | None            # None = unknown (provider gave nothing); never coerce to 0
    source: str                   # "provider_usage" | "estimate:chars_div_4"
    elapsed_ms: int = 0

def cost_usd(records: list[UsageRecord], model: str, prices: CostModel) -> float | None:
    row = prices.rows.get(model)
    if row is None or any(r.tokens is None for r in records): return None   # unknown, not zero
    ...
```

```markdown
<!-- docs/tool-optimizations.md — coverage matrix is generated; keep this marker pair -->
<!-- coverage-matrix:begin -->
| Form | Covered | Note |
...
<!-- coverage-matrix:end -->
```
The test regenerates the table from `coverage_matrix()` and compares it
to the text between the markers.

### Key Constraints
- Every measured number in the Markdown report carries its `source`
  label; median AND p95 are reported; `runs` ≥ 5 is enforced for
  `--live` (spec).
- The docs must state the tested host versions and that coverage was
  verified against those versions only.
- No em-dash-free requirement here, but keep the docs concise and
  copy-pasteable (commands in fenced blocks).
- `black`/`ruff` apply to `benchmarks/tool_optimizations/` too.

### References in Codebase
- `benchmarks/injection_guardrail_latency/` — existing benchmark layout and report style.
- `docs/mcp-local-toolkits.md` — tone and structure for tool docs.
- `sdd/specs/tool-optimizations.spec.md` §4 "Measurement Protocol", §5 AC15, §8.

---

## Acceptance Criteria

- [ ] `python -m benchmarks.tool_optimizations --scenario all --runs 1` (offline) writes JSON + Markdown under `artifacts/tool-optimizations/benchmarks/` and exits 0; the Markdown shows primary vs delegate vs total tokens, median/p95 latency, pass rate, cost `unknown` with the empty price table.
- [ ] `--live` refuses `--runs < 5` and is never exercised by tests.
- [ ] Offline harness test passes; coverage-matrix doc sync test passes.
- [ ] `docs/tool-optimizations.md` exists with every section listed in Scope, an AC1–AC15 traceability table, tested host versions, documented bypasses, and the release-gate paragraph.
- [ ] `docs/mcp-local-toolkits.md` links to it.
- [ ] Lint/format clean; tests: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_benchmark_harness.py -v`; log in `artifacts/logs/TASK-3092-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_benchmark_harness.py
import json, re
from pathlib import Path
import pytest
from benchmarks.tool_optimizations.runner import run, summarize, write_reports
from benchmarks.tool_optimizations.scenarios import SCENARIOS
from parrot_tools.tool_optimizations.hooks import coverage_matrix

ROOT = Path(__file__).resolve().parents[4]

async def test_offline_harness_all_scenarios(tmp_path):
    reports = [await run(s, mode, runs=1, workdir=tmp_path) for s in SCENARIOS for mode in ("baseline", "optimized")]
    summary = summarize(reports)
    out_json, out_md = write_reports(summary, ROOT / "artifacts" / "tool-optimizations" / "benchmarks", stamp="test")
    data = json.loads(out_json.read_text()); md = out_md.read_text()
    assert {"primary_tokens", "delegate_tokens", "total_tokens", "latency_median_ms", "latency_p95_ms", "pass_rate", "cost_usd"} <= set(data["scenarios"][0]["optimized"])
    assert data["scenarios"][0]["optimized"]["cost_usd"] is None        # unknown, not 0
    assert "primary" in md and "total" in md and "p95" in md
    assert all(r["optimized"]["pass_rate"] in (1.0, None) for r in data["scenarios"])

def test_docs_coverage_matrix_in_sync():
    doc = (ROOT / "docs" / "tool-optimizations.md").read_text()
    block = re.search(r"<!-- coverage-matrix:begin -->(.*?)<!-- coverage-matrix:end -->", doc, re.S).group(1)
    for row in coverage_matrix():
        assert f"| {row['form']} |" in block and ("yes" if row["covered"] else "no") in block

def test_docs_have_release_gate_and_traceability():
    doc = (ROOT / "docs" / "tool-optimizations.md").read_text()
    assert "owner decision" in doc and all(f"AC{i}" in doc for i in range(1, 16))
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3089, TASK-3090 and TASK-3091 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3092-benchmarks-docs-release.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5, session_01G9NM1TzdkFLd5foNDmh72K)
**Date**: 2026-09-10
**Notes**:

Created `benchmarks/tool_optimizations/` (7 files), `docs/tool-optimizations.md`
(357 lines), linked it from `docs/mcp-local-toolkits.md`, and added
`test_benchmark_harness.py`. 12 harness/doc tests; 372 passed + 1 skipped
across the whole feature suite; ruff and black clean.

## A real bug found while running the harness

The first end-to-end run died with
`NotImplementedError` from `asyncio.get_child_watcher()`. Cause: importing
`parrot` installs **uvloop's** event-loop policy as a side effect. The
runner imported the toolkits *lazily, inside* an already-running stdlib
loop, so the loop and the policy disagreed — `create_subprocess_exec` then
asked uvloop's policy for a child watcher it does not implement, and every
git call failed. Fixed with an explicit `_preload_toolkits()` before
`asyncio.run()`, documented in place. Worth remembering: any new
`asyncio.run()` entry point in this repo must import `parrot` **before**
starting the loop.

Second, smaller find: `writer_apply` requires a real git repository (it
re-checks the staged file list), which the benchmark fixture initially
lacked. That is correct product behaviour, not a defect, and is now stated
explicitly in the docs.

## Honest numbers, not flattering ones

The offline report is deliberately unvarnished. `targeted_read` shows the
expected large win (5,940 → 1,200 estimated primary tokens), but
`git_prepare` shows the optimized path costing **more** primary tokens than
the baseline (1,095 vs 6) — because the fixture repo has two files, so
terse git stdout is genuinely smaller than structured JSON results. Rather
than tune the fixture until the number looked good, that caveat is written
into `benchmarks/tool_optimizations/README.md` ("Reading the results
honestly") with a pointer to draw conclusions from `--live` runs on
representative repositories.

Accounting rules enforced by tests:

- **Unknown is never zero.** A missing provider count yields `None`, which
  propagates to `total_tokens=None` and `cost_usd=None`.
- **`prices.yaml` ships empty**, with `provenance` and `as_of` fields, so
  cost reads `unknown` until an operator supplies sourced figures.
- **Primary and delegate tokens are separate columns**, and the report text
  states outright that fewer primary tokens is not fewer total tokens.
- Exit code is driven by **correctness only** — an optimized scenario whose
  real pytest fails exits non-zero; token/latency numbers never fail a run.
- `--live` refuses fewer than five runs, and no test ever exercises it.

## Documentation

`docs/tool-optimizations.md` covers every section in scope. Two parts are
kept honest mechanically rather than by discipline:

- The **coverage matrix is generated from `hooks.coverage_matrix()`** and
  `test_docs_coverage_matrix_in_sync` re-derives it and compares row by
  row, so the published table cannot drift from the code.
- `test_docs_have_release_gate_and_traceability` asserts AC1–AC15 all
  appear in the traceability table, and
  `test_docs_record_tested_host_versions_and_bypasses` pins the tested host
  versions (Claude Code 2.1.267, codex-cli 0.154.0) and the documented
  bypasses.

The docs also record the per-host denial keyword difference discovered in
TASK-3091 (Claude `deny`, Codex `block`) and carry the Codex installer
format issue as an explicit **release checklist blocker**, asserted by
`test_docs_state_the_codex_release_blocker`.

## Release gate

**Numeric token, cost and latency targets are an owner decision (spec §8).**
This feature ships with correctness parity enforced by the harness and
reports the numbers it measured; no percentage saving is claimed anywhere
in the repository or the docs. The one substantive open decision from the
spec remains open by design — it was not invented here.

**Testing**: 12 tests in `test_benchmark_harness.py`; log at
`artifacts/logs/TASK-3092-pytest.log`. Reports at
`artifacts/tool-optimizations/benchmarks/` (gitignored).

**Deviations from spec**: none. Live-model benchmark runs are an operator
action, as the task scopes them; the command is documented and the harness
is ready.
