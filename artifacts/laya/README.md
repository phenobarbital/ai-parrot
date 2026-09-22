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

## Results of the review run (<date>)
<!-- FILL IN: table copied from results.json of the real run, or the exact `incomplete` reason if prerequisites were unmet -->

## Limitations
Smoke datasets; calibration is experimental; CPU timing depends on host; provider retries/fallback confound live latency/cost.
