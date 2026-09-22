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
The report includes:
- **Denominators**: `n_cases` (total cases), `n_ok` (successful predictions), `n_error` (failed predictions).
- **Confusion matrix**: Includes an `__error__` column for failed predictions.
- **Nearest-rank percentiles**: `p50` and `p95` are computed over the sorted inference times.
- **Prediction flips**: Cases where the prediction changed between the first and second runs.
- **Regex baseline**: For the injection scenario, the regex baseline is provided for comparison.
- **Route decisions**: For the routing scenario, the decisions and reasons are recorded.
- **Arms table**: For live routing, the arms table shows the primary and cheap model responses.
- **Model unverified**: If the model is not verified, it is marked as such.
- **Fallback samples**: Cases where the fallback mechanism was triggered.
- **Cost**: `null` if no `--price-file` is provided.
- **Status meanings**: `complete` (all scenarios executed), `incomplete` (some scenarios failed), `error` (unexpected failure).

## Results of the review run (2026-09-22)

**Not executed. The feature remains unverified for real CPU inference.** The orchestrating agent's
sandbox cannot install `laya`/`torch`/`transformers` (no network access to PyPI/Hugging Face and
no operator approval to create a task-local environment per this repo's dependency-installation
policy — worktree agents are read/execute-only against the shared `.venv`, and dependency
installation requires a real task-local environment with an explicit interpreter target or a
controlled installation by the main-checkout operator). Consequently:

- The isolated environment (`artifacts/laya/.venv`) and the checkpoint snapshot were never created.
- `python -m artifacts.laya.evaluate` was never run against real Laya inference.
- The opt-in `test_real_cpu_scenarios` / `test_live_paired_routing` tests were never exercised
  (they require `LAYA_EVAL_WORKER_PYTHON`/`LAYA_EVAL_CHECKPOINT`/`LAYA_EVAL_REVISION`, all absent
  here, so they remain skipped by design — a skip is not evidence, per spec §4).
- The M2 `_to_laya_questions`/`_from_laya_answers`/`load_predictor` `FILL IN`s in `worker.py`
  remain unresolved `NotImplementedError`/`None` placeholders. An earlier delivery attempt on this
  task replaced them with a guessed Laya answer shape (`raw[qid]["positive"]`, `raw[qid]["choice"]`,
  `agent.max_input_tokens`) without ever installing or importing the real `laya` package to confirm
  it — that is an unverified guess, not a verified call shape, and was reverted: the spec's
  Codebase Contract and Known Risks explicitly forbid claiming a verified external API shape
  without executing against the real dependency (`sdd/specs/laya-adoption.spec.md` §6 "Does NOT
  Exist", §7 "Known Risks / Gotchas": "SDK model metadata may repeat the requested model... no
  substitution").

**To close this gap**, an operator with approval to install packages and network access must:
1. Run the isolated-environment and checkpoint-snapshot commands above.
2. Resolve the three M2 `FILL IN`s in `artifacts/laya/worker.py` against the actually-installed
   `laya==0.3.5` `Agent`/`system_one` signatures (inspect `laya/agent.py` directly; do not guess).
3. Run `python -m artifacts.laya.evaluate ...` and the opt-in pytest suite, then paste the real
   `results.json` summary here.

Per spec §5 AC-8: "if prerequisites prevent execution, the feature remains unverified rather than
claiming end-to-end completion." Local-classifier evaluation was not claimed complete; no live
evidence is claimed either (no model IDs/credentials/cap were supplied — spec §8 U2).

## Limitations
Smoke datasets; calibration is experimental; CPU timing depends on host; provider retries/fallback confound live latency/cost.
