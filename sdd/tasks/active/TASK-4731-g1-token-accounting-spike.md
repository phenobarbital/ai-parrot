# TASK-4731: G1 — token-accounting spike (descriptor vs inline JSON)

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4739, TASK-4737
**Assigned-to**: unassigned

---

## Context

Spec §3 "Gate and Dependency Rules", gate **G1 — S1 token accounting**. The protocol's first goal (G-A) is receiver-token efficiency: an artifact result must cost the external LLM a bounded descriptor, never the payload. G1 measures that cost for a 10k-row frame with the real `HandleDescriptor` model (TASK-4739) and freezes the descriptor caps (preview rows, summary characters) that M6's `HandleAffordanceToolkit` and `HandleDescriptor` will enforce (AC20). This is a Lane-0 gate task: it produces a reproducible report and a proposed spec amendment, not production code.

---

## Scope

- Implement `sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py`: build a 10,000-row × 12-column pandas frame (mixed dtypes, deterministic seed), produce (a) the inline JSON result (`df.to_dict(orient="records")` serialized) and (b) a `HandleDescriptor` for it with configurable `preview_rows` and `summary` character cap; count tokens for both with two tokenizers.
- Tokenizers: `tiktoken` `cl100k_base` when importable, and the `len(text) / 4` heuristic always; when `PARROT_TEST_REAL_LLM=1` and an Anthropic client is configured, also the provider token count (optional third column).
- Write `report.md` (commands, versions, data provenance, raw numbers, pass/fail against the < 250-token criterion, and the **proposed amendment**: the frozen `preview_rows` / `summary_chars` / `max_sample_rows` / `max_text_tokens` values for spec §3 M6).
- Ship `packages/ai-parrot-squawk/tests/spikes/test_g1_token_accounting.py`: a pytest that re-runs the measurement in-process (heuristic tokenizer only, no network) and asserts the descriptor path stays under 250 tokens for the frozen caps; skipped unless `PARROT_SPIKE=1`.

**NOT in scope**: changing `HandleDescriptor` (TASK-4739 owns it; the amendment proposes the caps, a later task applies them), affordance tools (M6), any provider call beyond the optional real-LLM column.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py` | CREATE | Reproducible measurement script |
| `sdd/state/FEAT-746/spikes/G1-token-accounting/report.md` | CREATE | Gate report + proposed amendment |
| `packages/ai-parrot-squawk/tests/spikes/test_g1_token_accounting.py` | CREATE | Opt-in regression of the measurement |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interagent import HandleDescriptor, MediaType   # created by TASK-4739 (parrot/interagent/handles.py); verify it merged before starting
import pandas as pd            # core dependency (venv pandas 3.0.6)
import pyarrow as pa           # core dependency, packages/ai-parrot/pyproject.toml:180
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interagent/handles.py (TASK-4739)
class HandleDescriptor(BaseModel):   # frozen
    media_type: MediaType; byte_size: int; summary: dict[str, Any]
```

### Does NOT Exist
- ~~`parrot.squawk.client.affordances`~~ — M6 is gated on this very spike; do not import it.
- ~~`tiktoken` as a declared dependency~~ — import it inside `try/except ImportError`; the heuristic column is mandatory, tiktoken optional.
- ~~`polars`~~ — present in the venv transitively; MUST NOT be imported (spec U3, AC17).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-746/spikes/G1-token-accounting/report.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/spikes/test_g1_token_accounting.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Deterministic data (`numpy.random.default_rng(746)`); the report must be reproducible by re-running `python spike.py` from the repo root.
- The descriptor `summary` for arrow media is: `rows`, `columns: [{name, dtype}]`, `preview: [<preview_rows> row dicts]`, `null_counts` — this is the shape M6 will emit; the spike measures it, it does not redesign it.
- Report pass criterion (spec G1): descriptor path < 250 tokens for the 10k-row frame on both tokenizers; inline path measured for comparison.
- Logs under `artifacts/logs/`; nothing under `sdd/state/.../` may exceed a few KB besides the report.

### References in Codebase
- `sdd/state/FEAT-571/spikes/` — the gate-report layout this feature copies (FEAT-571 pattern).
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:328` — `_summary` is the existing compact-summary idiom.

---

## Implementation Blueprint

### Steps (in order)
1. Write `spike.py` with a `build_frame()`, `inline_payload(df)`, `descriptor_payload(df, preview_rows, summary_chars)` and `count_tokens(text) -> dict[str, int]` — *why*: each measurement must be re-runnable in isolation and reused by the pytest.
2. Sweep `preview_rows ∈ {3, 5, 10}` and `summary_chars ∈ {600, 1000, 1500}`; print a table — *why*: the amendment needs the largest caps that still pass < 250.
3. Write `report.md` from the table, naming the chosen caps — *why*: G1's output is the amendment, not the numbers alone.
4. Write the pytest around the chosen caps, gated by `PARROT_SPIKE=1` — *why*: the gate must stay reproducible after merge without network.

### `sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py` (CREATE)
```python
"""G1 — token accounting: descriptor path vs inline JSON for a 10k-row frame (FEAT-746)."""
from __future__ import annotations

import json
import sys
from typing import Any

import numpy as np
import pandas as pd

from parrot.interagent import HandleDescriptor, MediaType

ROWS, COLS, SEED = 10_000, 12, 746


def build_frame() -> pd.DataFrame:
    """Deterministic mixed-dtype frame (ints, floats, strings, dates, bools)."""
    rng = np.random.default_rng(SEED)
    # FILL IN: 12 columns — 4 int, 3 float, 3 str (department-like categories), 1 datetime, 1 bool — bounded by COLS
    raise NotImplementedError


def inline_payload(df: pd.DataFrame) -> str:
    """The JSON an A2A/REST call would put in context today."""
    return json.dumps(df.to_dict(orient="records"), default=str)


def descriptor_payload(df: pd.DataFrame, *, preview_rows: int, summary_chars: int) -> str:
    """JSON of the HandleDescriptor the external LLM would see."""
    summary: dict[str, Any] = {
        "rows": int(len(df)),
        "columns": [{"name": c, "dtype": str(t)} for c, t in df.dtypes.items()],
        "preview": json.loads(df.head(preview_rows).to_json(orient="records", date_format="iso")),
        "null_counts": {c: int(n) for c, n in df.isna().sum().items() if n},
    }
    text = json.dumps(summary, separators=(",", ":"))
    # FILL IN: truncate `text` to summary_chars by dropping preview rows first, then null_counts — bounded by summary_chars
    desc = HandleDescriptor(media_type=MediaType.ARROW, byte_size=int(df.memory_usage(deep=True).sum()), summary=json.loads(text))
    return desc.model_dump_json()


def count_tokens(text: str) -> dict[str, int]:
    """Heuristic always; tiktoken when importable."""
    out = {"heuristic_len4": len(text) // 4}
    try:
        import tiktoken  # optional, never declared

        out["tiktoken_cl100k"] = len(tiktoken.get_encoding("cl100k_base").encode(text))
    except ImportError:
        pass
    return out


def main() -> int:
    df = build_frame()
    print("inline", count_tokens(inline_payload(df)))
    for pr in (3, 5, 10):
        for sc in (600, 1000, 1500):
            print("descriptor", pr, sc, count_tokens(descriptor_payload(df, preview_rows=pr, summary_chars=sc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: the spec fixes the descriptor as the only thing the LLM sees (G-A, D3, D7) and G1 must freeze its caps with evidence. `HandleDescriptor` is imported, not re-declared, so the measurement is of the real model.

### `sdd/state/FEAT-746/spikes/G1-token-accounting/report.md` (CREATE)
```markdown
# G1 — Token accounting (FEAT-746)
- Commands: `source .venv/bin/activate && python sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py`
- Versions: python, pandas, pyarrow, tiktoken (or "absent")
- Data: build_frame() seed 746, 10,000 × 12
## Results
| path | preview_rows | summary_chars | heuristic | tiktoken |
<!-- FILL IN: table from spike output -->
## Verdict
PASS/FAIL against < 250 tokens (both tokenizers).
## Proposed amendment (spec §3 M6)
preview_rows = <N>; summary_chars = <N>; max_sample_rows = 50; max_text_tokens = 800   <!-- FILL IN from results -->
```

### `packages/ai-parrot-squawk/tests/spikes/test_g1_token_accounting.py` (CREATE)
```python
"""G1 regression — descriptor path stays under 250 heuristic tokens (opt-in)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PARROT_SPIKE") != "1", reason="spike: set PARROT_SPIKE=1")
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py"


def _load():
    spec = importlib.util.spec_from_file_location("g1_spike", SPIKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_descriptor_under_250_tokens():
    g1 = _load()
    df = g1.build_frame()
    # FILL IN: use the caps frozen in report.md — bounded by spec G1 (< 250 tokens)
    tokens = g1.count_tokens(g1.descriptor_payload(df, preview_rows=5, summary_chars=1000))
    assert tokens["heuristic_len4"] < 250
```

### FILL IN checklist
- [ ] `spike.py::build_frame` — column mix; bounded by 12 columns, deterministic seed
- [ ] `spike.py::descriptor_payload` — truncation order; bounded by `summary_chars`
- [ ] `report.md` — numbers and the chosen caps; bounded by < 250 tokens on both tokenizers

---

## Acceptance Criteria

- [ ] `python sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py` runs from the repo root and prints the sweep table
- [ ] `report.md` records versions, data provenance, the table, a PASS/FAIL verdict and the proposed caps
- [ ] Descriptor path < 250 tokens for the chosen caps on both tokenizers (spec G1 pass criterion, AC20)
- [ ] `PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g1_token_accounting.py -q` passes
- [ ] No `polars` import anywhere in the task's files

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/spikes/test_g1_token_accounting.py -q`

---

## Test Specification

See the blueprint test file; without `PARROT_SPIKE=1` the module is skipped, which is the expected default-tier result.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 G1 and §3 M6 (the caps you are freezing)
3. **Check dependencies** — TASK-4739 must be `"done"` in `sdd/tasks/index/inter-agent-protocol.json`
4. **Verify the Codebase Contract** before writing code
5. **Update status** in the index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `FILL IN`
7. **Verify** — run the Validation Commands with `PARROT_SPIKE=1`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4731 inter-agent-protocol verified`
10. **Fill in the Completion Note** — the proposed amendment MUST be quoted there verbatim

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
