# TASK-4832: Run the jailbreak bake-off and commit the evidence + pinned winner

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4831
**Assigned-to**: unassigned

---

## Context

Spec §5 hard gate: *"committed results under
`benchmarks/injection_guardrail_latency/results-jailbreak/` with per-candidate
manifest (model id, revision, sha256, license, verdict), threshold sweep, p50/p95
latency, startup/memory, and 0 Spanish-benign false positives at the selected
threshold for the pinned default — no default model constant lands before this."*

This task runs TASK-4831's harness against the real candidates and commits the
evidence. TASK-4835 reads the winner's model id / graph path / threshold / positive
labels **from the committed manifest**, and its tests assert the code constants match it.

> **Operator task.** Needs network (first HF download, ~0.3–1 GB per candidate),
> ~1–2 h CPU, and a human sign-off on the verdict and on the llama4 attribution
> condition if gravitee wins. Not suitable for an unattended coder seat.
> `madhurjindal/Jailbreak-Detector-Large` needs an ONNX export first:
> `python -m benchmarks.injection_guardrail_latency.export --model madhurjindal/Jailbreak-Detector-Large --output-dir <dir>`.

**If no candidate passes the gate**: commit the evidence anyway with
`"winner": null`; TASK-4835 then ships with NO default model id (engine resolves only
from `PARROT_JAILBREAK_ONNX_DIR` / `_MODEL`, heuristic floor otherwise) — record this as
`done-with-issues` and open a ledger issue for the follow-up model search.

---

## Scope

- Download/export candidates (eligible ones mandatory; 0din measured if reachable).
- Run `compare_jailbreak` at `max_length=512`, threads pinned, on this machine.
- Commit `results-jailbreak/manifest.json`, `results.json`, `README.md` (environment,
  CPU model, versions, verdict table, decision-rule restatement, llama4 note if relevant).
- Add a CI test that re-checks the committed manifest against the gate (fail-closed).

**NOT in scope**: guardrail code (TASK-4835); committing model weights or graphs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/injection_guardrail_latency/results-jailbreak/manifest.json` | CREATE | per-candidate manifest + winner |
| `benchmarks/injection_guardrail_latency/results-jailbreak/results.json` | CREATE | raw scores/latencies |
| `benchmarks/injection_guardrail_latency/results-jailbreak/README.md` | CREATE | human-readable verdict |
| `tests/benchmarks/test_jailbreak_bakeoff_manifest.py` | CREATE | fail-closed gate re-check |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from benchmarks.injection_guardrail_latency import compare_jailbreak as cj   # TASK-4831
# cj.ES_BENIGN_MAX_FP, cj.P50_BUDGET_MS, cj.CANDIDATES, cj.evaluate_gate, cj.pick_winner
```

### Existing Signatures to Use
```python
# benchmarks/injection_guardrail_latency/export.py — existing ONNX export CLI (FEAT-439)
# benchmarks/injection_guardrail_latency/results-v2-512/ — precedent layout for committed results
```

### Does NOT Exist
- ~~`results-jailbreak/`~~ — created here.
- ~~any model weights in git~~ — never commit `.onnx` / `.safetensors`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "benchmarks/injection_guardrail_latency/results-jailbreak/manifest.json", "action": "CREATE"},
    {"path": "benchmarks/injection_guardrail_latency/results-jailbreak/results.json", "action": "CREATE"},
    {"path": "benchmarks/injection_guardrail_latency/results-jailbreak/README.md", "action": "CREATE"},
    {"path": "tests/benchmarks/test_jailbreak_bakeoff_manifest.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Export madhurjindal to ONNX; download the others (fp32 gravitee only) — *why*: harness reads local graphs.
2. Run the harness; inspect per-bucket results by hand — *why*: a human must sanity-check before pinning.
3. Write README with the verdict; commit manifest/results — *why*: S9 reproducibility.
4. Add the manifest test — *why*: CI fails closed if someone edits the manifest into a non-passing winner.

### `tests/benchmarks/test_jailbreak_bakeoff_manifest.py` (CREATE)
```python
"""FEAT-761 TASK-4832 — the committed bake-off manifest satisfies the pre-registered gate."""
import json
from pathlib import Path

from benchmarks.injection_guardrail_latency import compare_jailbreak as cj

MANIFEST = Path(__file__).resolve().parents[2] / "benchmarks/injection_guardrail_latency/results-jailbreak/manifest.json"


def test_manifest_exists_and_lists_every_candidate():
    data = json.loads(MANIFEST.read_text())
    # FILL IN: every cj.CANDIDATES model_id present with sha256 + revision + license + verdict


def test_winner_meets_the_gate_or_is_null():
    data = json.loads(MANIFEST.read_text())
    # FILL IN: winner None allowed; else eligible, es_benign_fp <= cj.ES_BENIGN_MAX_FP,
    # p50_ms <= cj.P50_BUDGET_MS, threshold < 1.0, graph_path recorded (gravitee => "model.onnx")
```

### FILL IN checklist
- [ ] bake-off run + human review
- [ ] README verdict
- [ ] manifest test

---

## Acceptance Criteria

- [ ] Manifest/results/README committed; no weights committed.
- [ ] Winner (or `null`) consistent with the pre-registered rule; manifest test green.
- [ ] README records machine, versions, and the llama4 attribution condition if gravitee wins.

---

## Validation Commands

- `pytest tests/benchmarks/test_jailbreak_bakeoff_manifest.py -q`

---

## Test Specification

See CREATE block.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Confirm TASK-4831 is `done`. This is an operator task (network + human sign-off).
3. Mark `in-progress`; run; review; commit evidence + test.
4. Commit only listed files; `scripts/sdd/close_task.sh TASK-4832 agent-security-guardrails verified` (or `partial` with a null winner); fill the Completion Note with the winner and threshold.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Winner / threshold / graph**:
**Notes**:

**Deviations from spec**: none
