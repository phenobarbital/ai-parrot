# TASK-3618: README (isolated setup, snapshot, commands, interpretation) and real-CPU evidence run

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3616, TASK-3617, TASK-3609
**Assigned-to**: unassigned

---

## Context

Closes spec §3 **Module 5** and the runtime-readiness open question (§8): document the explicit,
approval-gated setup of the isolated Laya environment and checkpoint snapshot, then **run the real
CPU evaluation** and the opt-in real-CPU test to produce reports for review (AC-8). This is also
where M2's deferred verification happens: the Laya 0.3.5 call shape (`_to_laya_questions`,
`_from_laya_answers`, `load_predictor` kwargs) and the token-budget preflight versus the installed
runtime's serialization/truncation behaviour (spec §3 M2 "Verify this preflight … before marking
M2 complete").

If prerequisites cannot be met (no approval to install, no network for the snapshot, incompatible
runtime), the feature **remains unverified**: write the structured `incomplete` report the CLI
produces, record exactly what blocked, and say so in the Completion Note. Never claim end-to-end
completion from a mocked run (AC-8). Live evidence is conditional on the requester supplying
model IDs, a cap and credentials (§8 U2) and is not required to claim local-classifier evaluation only.

---

## Scope

- Create `artifacts/laya/README.md`: purpose and non-goals; isolated environment creation
  (`uv venv` + `uv pip install --python …`, approval note); checkpoint snapshot by immutable
  revision (`huggingface_hub.snapshot_download(repo_id, revision=…, local_dir=…)` from *inside* the
  isolated env) and how the report records revision + content hash; run commands for all
  scenarios, single scenario, and `--live`; env vars for the opt-in tests; how to read
  `results.json`/`report.md` (denominators, nearest-rank percentiles, `incomplete` statuses,
  `model_unverified`, the call-cap caveat); limitations (smoke datasets, no adoption gate).
- Verify and, if needed, fix the M2 `FILL IN`s in `artifacts/laya/worker.py` against the installed
  Laya 0.3.5 (`laya/agent.py`): question format, answer mapping, `max_input_tokens`, tokenizer used
  by the preflight, truncation flags off. Record the verified call shape in the Completion Note.
- Run: `python -m artifacts.laya.evaluate … --output-dir artifacts/laya/reports/<date>-cpu` (all
  scenarios, no `--live`), then `LAYA_EVAL_*` opt-in `pytest … -q` for `test_real_cpu_scenarios`,
  capturing output to `artifacts/logs/laya_evaluation_pytest.log`. If the requester has supplied
  live inputs, also run `--live` with the cap and the live test; otherwise state that live evidence is absent.

**NOT in scope**: changing any threshold after seeing results (tuning only on `calibration` cases, and
only if the requester asks); modifying workspace dependencies or lockfile; any production code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/README.md` | CREATE | Setup, commands, interpretation, limitations |
| `artifacts/laya/worker.py` | MODIFY | Only if runtime verification requires: Laya call-shape / tokenizer wiring fixes (else untouched) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21.

### Verified Imports
```python
# none new in repository code. Inside the isolated env only (worker.py FILL INs):
#   from laya import Agent            # spec §7: Agent(model_id_or_path, device, token, subfolder); .system_one(state, questions)
#   huggingface_hub.snapshot_download # runtime dependency of laya; used ONLY as a documented manual setup command
```

### Existing Signatures to Use
```python
# artifacts/laya/worker.py (TASK-3608/3609): LayaPredictor(agent, max_input_tokens, count_tokens); _to_laya_questions; _from_laya_answers; load_predictor
# artifacts/laya/evaluate.py (TASK-3616): python -m artifacts.laya.evaluate --worker-python --checkpoint-path --checkpoint-revision --output-dir [...]
# .gitignore:279 `artifacts/` ignored -> README must be `git add -f`; reports/logs/.venv/models under artifacts/laya stay untracked
# CLAUDE.md "Dependencies: Manage all dependencies via pyproject.toml" + spec §7 "subject to the repository's dependency-approval rule":
#   the isolated env is created ONLY when the operator approves; document it, do not automate it in the CLI.
```

### Does NOT Exist
- ~~a `make laya-setup` / automatic installer~~ — setup is manual and documented (spec §2).
- ~~a pinned Hugging Face repo id in this repository~~ — the README names the checkpoint repo id and revision the run used; both are also in `results.json` (`environment.worker.checkpoint_revision`, `checkpoint_sha256`).
- ~~numerical adoption gates~~ — the README's interpretation section explains the metrics; it draws no production-readiness conclusion (AC-11).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/README.md", "action": "CREATE"},
    {"path": "artifacts/laya/worker.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Do not create the isolated env or download weights without operator approval; ask (Completion Note / session) and,
  if unattended, write the `incomplete` report and stop. `uv sync` is never used (worktree rule); the env is
  `artifacts/laya/.venv` via `uv venv artifacts/laya/.venv --python 3.12` then
  `uv pip install --python artifacts/laya/.venv/bin/python -e artifacts/laya` (+ `huggingface_hub[cli]` if needed).
- Reports directory: `artifacts/laya/reports/<YYYY-MM-DD>-cpu[-live]` — must be new (CLI refuses non-empty).
- Record in the Completion Note: distribution name+version+hash (`pip show`/`uv pip show`), torch/transformers
  versions, checkpoint repo id, revision, `checkpoint_sha256`, CPU model/threads, cold startup ms, warm p50/p95,
  peak RSS, per-scenario accuracy with denominators, error/abstention counts, regex-baseline agreement, and the
  verified Laya call shape. No adoption conclusion.
- If `worker.py` changes, re-run `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_worker.py packages/ai-parrot/tests/unit/laya_eval/test_laya_context_limits.py -q`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the README skeleton (headings below) — *why*: the CLI's incomplete report already points users at these section names (TASK-3616).
2. Obtain approval; create the isolated env; install; `pip show laya` — *why*: spec §7 dependency-approval rule.
3. Snapshot the checkpoint by revision into `artifacts/laya/models/<name>@<rev>` — *why*: immutable identity (spec §2).
4. Inspect the installed `laya/agent.py`; complete/fix worker `FILL IN`s; run worker unit tests — *why*: M2 verification gate.
5. Run the CLI (all scenarios) and the opt-in test; save outputs — *why*: AC-8 evidence.
6. Fill the README interpretation section from the real report; `git add -f artifacts/laya/README.md` (+ worker.py if changed).

### `artifacts/laya/README.md` (CREATE — skeleton)
```markdown
# Laya CPU evaluation (FEAT-589)

Exploratory evaluation of Laya typed decisions for (1) prompt-injection classification vs the regex baseline,
(2) same-provider model routing inside an assigned AI-Parrot Agent, (3) document-grounded categorization.
English, CPU only. **No production adoption gate is derived from these numbers** (spec §5 AC-11).

## What it is not
Production adoption; Jev replacement; guardrail changes; PII; training/ONNX; GPU/multilingual; streaming/tool routing.

## Isolated environment (explicit, approval-gated)
    uv venv artifacts/laya/.venv --python 3.12
    uv pip install --python artifacts/laya/.venv/bin/python -e artifacts/laya
    artifacts/laya/.venv/bin/python -c "import laya, torch; print(laya.__version__, torch.__version__)"
Nothing in the CLI installs packages or downloads weights. Never `uv sync` here.

## Checkpoint snapshot (immutable revision)
    artifacts/laya/.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('<repo_id>', revision='<rev>', local_dir='artifacts/laya/models/<name>@<rev>')"
The report records `checkpoint_revision` and a content hash over the snapshot's weights/config files.

## Run
    python -m artifacts.laya.evaluate --worker-python artifacts/laya/.venv/bin/python \
      --checkpoint-path artifacts/laya/models/<name>@<rev> --checkpoint-revision <rev> \
      --output-dir artifacts/laya/reports/$(date +%F)-cpu
Single scenario: `--scenario injection|routing|grounded`. Exit codes: 0 complete, 2 invalid configuration, 3 incomplete/error.

### Live paired routing (opt-in, costs money)
Requires `--live --primary-api-model <id> --cheap-api-model <id> --max-live-calls <n>` and `ANTHROPIC_API_KEY`.
`--primary-label anthropic:opus-5` is the requested preference and is recorded; the provider id is what is sent.
The cap counts logical `Agent.ask` calls (both arms, failures included); it is not an HTTP-attempt or money cap.

## Tests
    pytest packages/ai-parrot/tests/unit/laya_eval -q          # mocked, offline
    pytest packages/ai-parrot/tests/integration/test_laya_evaluation.py -q
Opt-in real CPU: `LAYA_EVAL_WORKER_PYTHON`, `LAYA_EVAL_CHECKPOINT`, `LAYA_EVAL_REVISION`. Opt-in live: `LAYA_EVAL_LIVE=1` + model ids + cap + key.
Skipped tests are skips, not evidence. Log: `artifacts/logs/laya_evaluation_pytest.log`.

## Reading the report
<!-- FILL IN: denominators (n_cases/n_ok/n_error), confusion matrix incl. __error__ column, nearest-rank p50/p95 definition,
     prediction_flips, regex baseline + framework-stripping note, route decisions and reasons, arms table, model_unverified,
     fallback samples, cost=null without --price-file, status meanings — bounded by spec §4 reporting paragraph -->

## Results of the review run (<date>)
<!-- FILL IN: table copied from results.json of the real run, or the exact `incomplete` reason if prerequisites were unmet -->

## Limitations
Smoke datasets; calibration is experimental; CPU timing depends on host; provider retries/fallback confound live latency/cost.
```
**Why this shape**: spec §3 M5 "explicit environment/weight setup, commands and interpretation" and
§2 "Missing dependencies/snapshot produce … actionable instructions" — the CLI's limitation text
points to the two section titles used above.

### `artifacts/laya/worker.py` (MODIFY — conditional)
```python
# occurrences: 1 (verified at execution time: grep -c '^def _to_laya_questions' artifacts/laya/worker.py)
# REPLACE the bodies of _to_laya_questions / _from_laya_answers / load_predictor's Agent(...) kwargs and max_input_tokens ONLY
# where the installed laya 0.3.5 differs from the TASK-3608 FILL INs. Keep signatures. Keep `device="cpu"`.
# FILL IN: verified shape from artifacts/laya/.venv/lib/python3.12/site-packages/laya/agent.py — bounded by spec §3 M2 + §7 external contracts
```
**Why**: this is the only sanctioned place to reconcile the spec's inspected-upstream contract with the pinned, installed runtime.

### FILL IN checklist
- [ ] README "Reading the report" and "Results of the review run"
- [ ] worker.py call-shape/tokenizer verification (record outcome even when no change was needed)

---

## Acceptance Criteria

- [ ] AC-1 — README documents isolated setup, snapshot-by-revision, run commands, test opt-ins, interpretation and limitations (spec AC-1, AC-10).
- [ ] AC-2 — Either real CPU reports exist under `artifacts/laya/reports/…` (untracked) with `environment.worker.device == "cpu"` and all three scenarios executed (spec AC-2, AC-8), **or** the Completion Note states precisely why the feature remains unverified.
- [ ] AC-3 — The Laya call shape and the preflight tokenizer are verified against the installed runtime and recorded (spec §3 M2, §8).
- [ ] AC-4 — No change under `packages/`, `pyproject.toml`, `uv.lock` (spec AC-10); no adoption conclusion anywhere (spec AC-11).
- [ ] AC-5 — Worker unit tests still pass if `worker.py` changed.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_worker.py -q`
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_context_limits.py -q`
- `pytest packages/ai-parrot/tests/integration/test_laya_evaluation.py -q`

---

## Test Specification

The opt-in `test_real_cpu_scenarios` (TASK-3617) is the executable check for this task when the
`LAYA_EVAL_*` variables point at the environment created here; paste its non-skipped output into the Completion Note.

---

## Agent Instructions

1. Read spec §2 "Overview", §3 Module 2 (verification sentence), §5 AC-8/AC-10/AC-11, §7, §8.
2. Confirm TASK-3616, TASK-3617 and TASK-3609 are completed.
3. Ask for (or confirm) approval before creating the isolated environment and downloading weights; without it, produce the `incomplete` report and document the blocker.
4. Follow the Steps; `git add -f artifacts/laya/README.md` (and `worker.py` if changed); commit; move this file; update the index; fill the Completion Note with the evidence table.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
