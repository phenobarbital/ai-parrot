# Laya capability evaluation (FEAT-589)

A runnable CPU evaluation of prompt-injection detection, model-routing decisions and
classification grounded in a supplied document. The CLI produces JSON evidence and a
Markdown report. It uses real Laya 0.3.5 inference in an isolated subprocess; optional
paired Anthropic or Google Agent calls measure downstream routing outcomes.

The scope is English smoke evaluation, not production Jev replacement, PII redaction,
multilingual benchmarking or a production guardrail. Laya's checkpoint selection and
AI-Parrot's downstream model routing are different decisions.

## Setup

Run from the repository root. The worker environment is separate from the workspace;
these commands install the existing evaluation dependency without changing the root lockfile:

```bash
source .venv/bin/activate
uv venv artifacts/laya/.venv --python 3.12
uv pip install --python artifacts/laya/.venv/bin/python -e artifacts/laya
```

Download the English checkpoint explicitly, pinned to the revision tested here:

```bash
source artifacts/laya/.venv/bin/activate
python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    'convaiinnovations/laya',
    revision='85cc74ddae6109077ebe2853a9b3077fb6606a78',
    local_dir='artifacts/laya/models/85cc74ddae6109077ebe2853a9b3077fb6606a78',
    allow_patterns=['rl_agent_config.json', 'model.safetensors', 'tokenizer/*', 'encoder/*'],
)
PY
source .venv/bin/activate
```

Both the local tokenizer and encoder config are required. Evaluation forces Hugging Face
and Transformers offline mode; it never installs packages or fetches missing weights.
The upstream loader can normalize tokenizer configuration on disk, so the report records
checkpoint hashes both before and after loading. Hashing reads weights in bounded chunks.

## Run all capabilities

```bash
source .venv/bin/activate
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 python -m artifacts.laya.evaluate \
  --worker-python artifacts/laya/.venv/bin/python \
  --checkpoint-path artifacts/laya/models/85cc74ddae6109077ebe2853a9b3077fb6606a78 \
  --checkpoint-revision 85cc74ddae6109077ebe2853a9b3077fb6606a78 \
  --warmup 1 --repeats 3 \
  --output-dir artifacts/laya/reports/my-evaluation
```

Choose a new output directory each time. Add `--scenario injection`, `--scenario routing`
or `--scenario grounded` to select one capability. `--help` requires no Laya installation.

Exit codes: **0** complete requested evaluation, **2** invalid configuration, **3** incomplete
or failed evaluation. The all-scenarios command above intentionally returns **3** because
paid downstream routing calls are disabled. Local inference results remain valid and visible;
this is distinct from an inference failure. Injection-only and grounded-only runs can return 0.

## Optional live Agent routing

Add these flags to run paired primary-only and routed Agent calls:

```text
--live --primary-api-model <provider-id> --cheap-api-model <provider-id> --max-live-calls 16
```

Set `ANTHROPIC_API_KEY` in the environment. Eight default routing fixtures require 16 logical
calls for one pair per fixture. `--max-output-tokens` defaults to 256. SDK retries can produce
more HTTP attempts; the logical-call cap is not a monetary cap. No live calls occur by default.

Both IDs use the provider selected by `--provider anthropic|google` (default: Anthropic). Selection is request-local and leaves the
client's default model untouched. Invalid predictions, abstention and confidence below
`--routing-threshold` (default 0.8) retain the primary model. The client fallback model is an
availability fallback, not proof of a cheaper model; supply the model pair explicitly.
The historical `--primary-label anthropic:opus-5` is descriptive only, never an inferred API ID.

Reports distinguish requested, selected and provider-returned models. Missing model evidence,
provider errors and exhausted budgets remain incomplete. Costs are null without `--price-file`;
prices must use actual returned model IDs, with `input_per_1k` and `output_per_1k` values.

## Fixtures and evidence

`--fixtures <directory>` accepts the same JSONL schema as `fixtures/`, plus
`routing_rubrics.json` for routing. Keep unique case IDs and disjoint calibration/evaluation
states. Never tune thresholds on held-out evaluation cases. The default aggregate is a smoke
summary across both splits, not a held-out accuracy claim. Each local sample records its split,
typed answers/probabilities, expected/predicted label, timings and any operational error.

The worker preserves the positive `noul` probability separately from confidence. Its token
preflight uses the real tokenizer and Laya 0.3.5 sequence format, including option markers and
special delimiters. It rejects state, instruction and option truncation before inference.
Laya itself replaces literal mask tokens with spaces; this upstream normalization also applies
in preflight. Every question has its own token budget.

Reports include fixture hashes, checkpoint hashes/revision, runtime versions, device, thread
count, load/startup timing, peak RSS, confusion matrices, errors, prediction flips, nearest-rank
p50/p95 and routing decisions. Accuracy uses repeat zero; timing uses all measured repeats.
Warmup is excluded. Injection results include the regex baseline on identical texts; the regex
engine strips its allowlisted framework wrappers. An operational failure never counts as success.

## Verified CPU results

A real run on 2026-11-10 used Python 3.12.3, Laya 0.3.5, Torch 2.15.0,
Transformers 5.22.2 and four CPU threads. All 34 fixtures ran twice without inference errors:

| Capability | Correct / fixtures | Warm inference p50 / p95 |
|---|---:|---:|
| Injection detection | 15 / 16 | 266.6 / 347.9 ms |
| Routing label classification | 3 / 8 | 271.3 / 349.3 ms |
| Document-grounded classification | 8 / 10 | 285.0 / 315.9 ms |

Startup was 30.9 s; peak RSS was about 3.12 GiB. No predictions changed between repeats.
After the confidence policy, all eight routing requests retained primary. This run shows
execution capability, not demonstrated model-cost savings or production security quality.
The small dataset and routing errors argue for a larger held-out evaluation before adoption.
The upstream temperature warning concerns its 11+ choice bucket; these fixtures use 2, 3 or 5 options.

Local evidence: `reports/completion-cpu-2/results.json` and `report.md` (two-pass initial run),
`reports/completion-verified/` (final three-pass run including per-sample probabilities/splits).
Regression validation: **106 passed, 1 skipped** (the paid-provider test), including real CPU
integration; exact tokenizer boundary checks passed. Formatting and focused Ruff checks passed.
Environments, weights, generated reports and logs stay untracked. The older 2026-09-22
review had no real inference evidence; its unresolved adapter placeholders are now implemented.
The CPU completion run did not execute paid calls; see the Google verification follow-up below.

## Validation

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/unit/laya_eval \
  packages/ai-parrot/tests/unit/test_laya_evaluation.py \
  packages/ai-parrot/tests/integration/test_laya_evaluation.py -q
```

To include real CPU integration, set `LAYA_EVAL_WORKER_PYTHON`, `LAYA_EVAL_CHECKPOINT`
and `LAYA_EVAL_REVISION` to the interpreter, snapshot and revision above. For paid integration
also set `LAYA_EVAL_LIVE=1`, `LAYA_EVAL_PRIMARY_API_MODEL`, `LAYA_EVAL_CHEAP_API_MODEL`,
`LAYA_EVAL_MAX_LIVE_CALLS` and `ANTHROPIC_API_KEY`. Skipped tests are not live evidence.
Completion logs are in `artifacts/logs/laya_completion_*.log`.

## Google paid verification

Use the same interpreter/checkpoint flags from the CPU command, with:

```text
--scenario routing --live --provider google
--primary-label google:gemini-3.5-flash --primary-api-model gemini-3.5-flash
--cheap-api-model gemini-3.1-flash-lite --max-live-calls 16 --max-output-tokens 1024
```

The comparison model is the existing Google client's fallback. Credentials use `GOOGLE_API_KEY`
through the same environment/project configuration as that client. Google evidence uses raw
`model_version` (or `modelVersion`), never the requested `AIMessage.model`. If Google resolves
an alias to another version, both identifiers remain visible. These calls still use AI-Parrot
Agent dispatch, not a direct SDK invocation. The default routing threshold remains 0.8.

For the opt-in integration test, set `LAYA_EVAL_PROVIDER=google`, `GOOGLE_API_KEY` and the
existing `LAYA_EVAL_*` model, call-cap and worker variables. Optional
`LAYA_EVAL_MAX_OUTPUT_TOKENS` defaults to 1024 for that integration test.

### Paid run results (2026-11-10)

- Eight fixtures × two arms: **16 successful paid Agent responses**, 264 prompt tokens and
  3,308 completion tokens. The original report remains `incomplete`: its extractor omitted
  the real client's `google_genai` provider tag, so actual-model evidence was not retained.
  Evidence: `reports/google-live-verified/results.json` (the directory name does not imply a pass).
- After adding and regression-testing that tag, a separate one-fixture, two-call confirmation
  completed with **both provider model versions verified**, 28 prompt tokens and 14 completion
  tokens. Evidence: `reports/google-live-confirmed/results.json` and `report.md`; CLI exit 0.
- Requested **`gemini-3.5-flash`**, provider returned **`gemini-3.6-flash`** in both confirmed calls.
  This confirms actual paid execution through the requested ID, not execution of a 3.5 checkpoint.
- All decisions retained primary at the unchanged 0.8 routing threshold. The configured fallback
  `gemini-3.1-flash-lite` was not selected or exercised. No savings claim is supported.
- Total: **18 successful paid logical calls**. No price table was supplied; cost remains null.
  The earlier sandbox attempt failed DNS before receiving a provider response and was stopped.
- Literal rubric pass rate was 0 in the eight-case run: even “The capital of France is Paris.”
  fails an exact `Paris` rubric. Treat this as a rubric limitation, not semantic answer accuracy.
  No rubric or threshold was tuned after observing the paid answers.

Validation: broader offline suite 109 passed / 2 skipped before the provider-tag correction;
final affected tests 29 passed / 2 skipped (real tests intentionally opt-in), plus the verified
paid CLI confirmation and passing Ruff/format checks. Logs: `artifacts/logs/laya_google_*.log`.

Committed evidence summary (including original report hashes):
`sdd/state/FEAT-589/verification/evaluation-summary.json`. Generated reports and logs remain local.
