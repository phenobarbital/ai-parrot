# TASK-3624: Delegate backend spike + decision record

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Spike first" and AC1: before any backend is built, measure whether
Needle 3 (base weights) and a llama.cpp-served GGUF model can reliably propose
calls for real ai-parrot toolkits. The decision record this task commits gates
TASK-3632 (LlamaCppDelegate), TASK-3633 (NeedleDelegate) and TASK-3637
(extras pin). The protocol, plan language, validator and node do not depend on
it. Implements spec Module 0.

This task is **not delegation-eligible**. It needs model downloads, a local
`llama-server`, and judgment about what the numbers mean. The orchestrator or
a human should run it, not an `sdd-coder` seat. It also writes under
`sdd/state/`, which coder seats must not touch.

---

## Scope

- Write a standalone probe script with no dependency on the plan module:
  - a minimal Needle probe (`needle.Needle(tools=..., weights=...)` →
    `.complete(text)`, no pool)
  - a minimal llama.cpp probe (HTTP `POST` to `llama-server` with a
    `json_schema` constraint)
- Build 50–100 cases in JSONL drawn from real ai-parrot toolkits (web
  scraping, HTTP, DB/query, working memory). Include ≥ 10 abstention cases
  where no tool fits, and a spread of instruction lengths.
- Measure per backend:
  - exact match (tool name + arguments)
  - abstention precision/recall
  - latency p50/p95, including Needle via `ProcessPoolExecutor` vs.
    `asyncio.to_thread`
  - behaviour as the instruction gets longer, and the observed usable
    `max_input_chars`
  - confidence calibration (Needle) and logprob availability (llama.cpp)
- Write the decision record, applying the spec §2 rules verbatim:
  - Needle ≥ 90% → Needle is primary (option A).
  - Needle < 90% but llama.cpp ≥ 90% → llama.cpp is primary (option C).
  - Both < 90% → fine-tune first (option B). If still below 90%, drop the
    feature and state what happens to the merged tasks.
- Record the exact `cactus-needle` version, the GGUF model, and the
  `llama-server` build tested.

**NOT in scope**: the `ToolCallDelegate` protocol (TASK-3627), the production
backends (TASK-3632/3633), fine-tuning itself, and pyproject changes
(TASK-3637).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/spikes/tool_call_delegate_spike.py` | CREATE | Probe harness + metrics |
| `sdd/state/FEAT-590/spike/cases.jsonl` | CREATE | 50–100 eval cases |
| `sdd/state/FEAT-590/spike/decision.md` | CREATE | Metrics + decision record (AC1) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp                     # core dependency (packages/ai-parrot/pyproject.toml dependencies)
from pydantic import BaseModel, Field
# needle is NOT installed in the venv — `uv pip install cactus-needle` into a scratch env, or
# `uv run --no-sync --with cactus-needle` — never `uv add` in this task (pyproject is TASK-3637's).
```

### Existing Signatures to Use
```python
# Tool schemas for the cases — take them from live toolkits, via:
# packages/ai-parrot/src/parrot/tools/abstract.py:591
class AbstractTool:
    def get_schema(self) -> Dict[str, Any]   # {"name","description","parameters"}; context fields stripped
```

### Does NOT Exist
- ~~`scripts/spikes/`~~: the directory does not exist yet; create it.
- ~~A verified `cactus-needle` API~~: `needle.Needle(tools=, system=, weights=)`, `.complete()`, `.reset()`, the response keys `function_calls`/`confidence` all come from proposal §A.1 and are **unverified**. Verifying them is this task's job. Record any divergence in the decision record.
- ~~`agent.run()`~~: must not be used. It executes Python functions itself.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/spikes/tool_call_delegate_spike.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-590/spike/cases.jsonl", "action": "CREATE"},
    {"path": "sdd/state/FEAT-590/spike/decision.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.get_schema"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async harness (`asyncio.run(main())`). Use aiohttp for llama-server; no `requests`/`httpx`.
- Use a logger, not `print`, except for the final metrics table, which may go to stdout from `main()`.
- Keep cases realistic: take the tool schemas from real toolkits via `get_schema()`, not hand-written ones.

---

## Implementation Blueprint

### Steps (in order)
1. Create `scripts/spikes/tool_call_delegate_spike.py` from the block below — *why*: one reproducible harness, re-runnable after a fine-tune.
2. Write `cases.jsonl`: one object per line, `{"id","instruction","facts","tools":[<schema>...],"expected":{"name":..., "arguments":{...}} | null}` — *why*: `expected=null` encodes the abstention cases.
3. Run it against each available backend and paste the metrics into `decision.md` — *why*: AC1 requires the numbers next to the decision.
4. Apply the §2 decision rules verbatim in `decision.md` — *why*: downstream tasks read this record, not the spike output.

### `scripts/spikes/tool_call_delegate_spike.py` (CREATE)
```python
"""FEAT-590 spike: measure tiny local tool-calling backends on ai-parrot toolkits."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from pydantic import BaseModel, Field

logger = logging.getLogger("feat590.spike")


class CaseResult(BaseModel):
    """One case scored against one backend."""

    case_id: str
    backend: str
    exact_match: bool
    abstained: bool
    expected_abstain: bool
    confidence: Optional[float] = None
    latency_ms: float = Field(ge=0.0)


class SpikeReport(BaseModel):
    """Per-backend aggregate metrics."""

    backend: str
    cases: int
    exact_match: float
    abstention_precision: float
    abstention_recall: float
    latency_p50_ms: float
    latency_p95_ms: float


async def probe_llamacpp(session: aiohttp.ClientSession, url: str, case: Dict[str, Any]) -> CaseResult:
    """POST one case to llama-server with a oneOf json_schema; score it."""
    # FILL IN: build oneOf [{name: const, arguments: schema}] + {name: null}; call /completion or
    #   /v1/chat/completions (record which one worked in decision.md) — bounded by spec M6
    raise NotImplementedError


def probe_needle(case: Dict[str, Any], weights: Optional[str]) -> CaseResult:
    """Run one case through needle.Needle(...).complete() — blocking; called via executor."""
    # FILL IN: lazy `import needle`; verify API shape against proposal §A.1 — bounded by AC1
    raise NotImplementedError


def summarize(results: List[CaseResult]) -> SpikeReport:
    """Aggregate CaseResults for one backend."""
    # FILL IN: exact_match rate; abstention precision/recall; p50/p95 via statistics.quantiles
    raise NotImplementedError


async def run_spike(cases_path: Path, *, needle: bool, llamacpp_url: Optional[str]) -> List[SpikeReport]:
    """Run every case against each enabled backend; return per-backend metrics."""
    cases = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
    logger.info("loaded %d cases", len(cases))
    # FILL IN: per-backend loops; Needle through ProcessPoolExecutor AND asyncio.to_thread (latency comparison)
    raise NotImplementedError


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("sdd/state/FEAT-590/spike/cases.jsonl"))
    parser.add_argument("--needle", action="store_true")
    parser.add_argument("--llamacpp-url", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    reports = asyncio.run(run_spike(args.cases, needle=args.needle, llamacpp_url=args.llamacpp_url))
    for report in reports:
        logger.info("%s", report.model_dump_json())


if __name__ == "__main__":
    main()
```
**Why this shape**: pure metrics collection with no import of `parrot.bots.flows.plan`, so the spike stays valid even if the architecture tasks are mid-flight. `time`/`statistics` are there for the latency percentiles.

### `sdd/state/FEAT-590/spike/decision.md` (CREATE)
```markdown
# FEAT-590 spike — decision record
- Date / operator:
- cactus-needle version: · GGUF model: · llama-server build:
## Metrics (per backend): cases · exact_match · abstention P/R · p50 · p95 · max usable input chars
## Needle executor: process | thread — evidence:
## Confidence: Needle calibration · llama.cpp logprobs usable? (yes/no)
## Decision (spec §2 rules): primary = needle | llamacpp · option = A | B | C | DROP
## Consequences for TASK-3632 / TASK-3633 / TASK-3637 (and M1–M5/M8 if DROP)
```
**Why**: TASK-3632/3633/3637 read these exact headings.

### FILL IN checklist
- [ ] `probe_llamacpp` — request shape; bounded by spec M6 (oneOf + decline branch)
- [ ] `probe_needle` — API verification; bounded by AC1 (record divergences)
- [ ] `summarize` — metric math
- [ ] `run_spike` — executor comparison for Needle
- [ ] `cases.jsonl` — ≥ 50 cases, ≥ 10 abstentions, real toolkit schemas
- [ ] `decision.md` — every heading filled; decision follows §2 rules exactly

---

## Acceptance Criteria

- [ ] `decision.md` contains ≥ 50 cases' metrics per available backend, and a decision under the spec §2 rules (AC1)
- [ ] It records the tested `cactus-needle` version (for TASK-3637), the Needle executor choice (for TASK-3633) and logprob usability (for TASK-3632)
- [ ] `ruff check scripts/spikes/tool_call_delegate_spike.py` is clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/plan/test_plan.py -q`

> The spike has no unit tests of its own. This command only proves the
> spike didn't disturb the plan package. The real validation is the
> decision record.

---

## Test Specification

None (spike). The evidence is `decision.md`.

---

## Agent Instructions

1. Read the spec (§2 "Spike first", §5 AC1).
2. Verify the Codebase Contract.
3. Implement from the blueprint, run it, write the record.
4. Commit the three files. Move this task to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
