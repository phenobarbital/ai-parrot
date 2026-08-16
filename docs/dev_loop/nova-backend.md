# Dev-loop `nova` backend (AWS Bedrock)

FEAT-405 adds a single **`nova`** dev-loop backend that reaches
AWS-Bedrock-hosted models through one AWS credential, spanning three seats
in the dev-loop flow. This document is the operator reference: what it is,
how to configure it, and what to expect until its soft dependency
(FEAT-404) lands.

This feature is **purely additive** ([R3]): an operator who configures
nothing sees byte-identical behaviour to before this feature —
`claude-code` still develops, `codex` still reviews adversarially, and
`nodes/research.py` is unmodified.

## The three seats

| Seat | Role | Default model | Shape | Transport |
|---|---|---|---|---|
| Development | dev-agent-pool worker (`agent: "nova"`) | `minimax.minimax-m2.5` | tool loop | `bedrock-mantle` (OpenAI-compatible) → `NovaCodeDispatcher` |
| Adversarial review | read-only second opinion | `us.amazon.nova-2-lite-v1:0` | no tools, one call | Converse — `NovaAdversarialReviewDispatcher` / `NovaClient.ask()` |
| Mechanical (PR enrichment) | "Summary of changes" section | `us.amazon.nova-2-lite-v1:0` | no tools, one call | Converse — `NovaClient.ask()` |

Both Converse seats default to Amazon's **own** Nova models, not to
`us.anthropic.*` ids. Bedrock gates every Anthropic model behind a
per-account *"Anthropic use case details"* form, so an account holding a
valid Bedrock API key still gets
`ResourceNotFoundException: Model use case details have not been submitted
for this account` on the first call. Native Nova ids need no such form,
which makes them the correct default for a *Nova* backend. Deployments that
have completed the Anthropic form can point either key back at a
`us.anthropic.*` id — the ids stay curated and selectable.

A Claude model **cannot** hold the `nova` development seat: Bedrock offers
no Chat Completions API for the Anthropic family, so the dev seat is
limited to models Bedrock serves over `bedrock-mantle` (MiniMax, Kimi,
GLM). A Claude development seat is served by the existing `claude-code`
backend instead.

### Curated model ids (verified against the Bedrock model cards)

| Model | Bedrock id | Notes |
|---|---|---|
| MiniMax M2.5 | `minimax.minimax-m2.5` | dev seat default; output capped at 8K tokens |
| Kimi K2.5 | `moonshotai.kimi-k2.5` | dev seat alternative; output capped at 16K tokens |
| Z.ai GLM-5 | `zai.glm-5` | dev seat alternative; output capped at 128K tokens |
| Nova 2 Lite | `us.amazon.nova-2-lite-v1:0` | adversarial-review **and** mechanical-seat default; geo/global only (`us.`/`eu.`/`jp.`/`global.`) — **no in-region access**, the `us.` prefix is required |
| Nova Pro | `us.amazon.nova-pro-v1:0` | Converse alternative for either no-tools seat (previous Nova generation) |
| Claude Opus 5 | `us.anthropic.claude-opus-5` | selectable for the adversarial seat; requires the per-account Anthropic use-case form; no in-region access in us-west-2/us-east-2 — needs a geo/global prefix |
| Claude Haiku 4.5 | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | selectable for the mechanical seat; requires the per-account Anthropic use-case form |
| Claude Fable 5 | `global.anthropic.claude-fable-5` | available via `translate()`; not a default for any seat |

None of `minimax.minimax-m2.5` / `moonshotai.kimi-k2.5` / `zai.glm-5` have
a geo or global inference profile — they are never region-prefixed,
regardless of `region_prefix` (see `models/bedrock_models.py`'s
`REQUIRES_REGION_PREFIX` allowlist).

## Enabling the dev seat

Add `nova` to the pool's agent specs (`DEV_LOOP_DEV_AGENTS`, or a
programmatic `DevAgentPoolConfig`), e.g.:

```json
{"agents": [{"agent": "nova", "model": "minimax.minimax-m2.5", "count": 1}]}
```

`build_dispatcher` resolves it to `(NovaCodeDispatcher,
NovaCodeDispatchProfile)`, exactly like every other backend branch.

## Enabling the adversarial seat

The adversarial seat defaults to `codex` (`ADVERSARIAL_BACKEND`,
`catalog.py`) — unchanged. Set `DEV_LOOP_ADVERSARIAL_BACKEND=nova` to
select the Nova reviewer instead. Any other value raises a clear error
naming both valid options (`codex`, `nova`).

The Nova adversarial reviewer is read-only **by construction**: it is
never handed a tool at all (not a sandboxed profile — the model literally
has no tool configuration to invoke), and its verdict always reports
`files_modified == []` regardless of what the model claims.

## Credentials — two paths

Bedrock Converse (adversarial + mechanical seats, via `NovaClient`) and
`bedrock-mantle` (dev seat) use **different** credential mechanisms:

1. **SigV4 (access/secret keypair or an AWS profile)** — the standard
   `BedrockConverseBase` resolution: explicit `aws_access_key`/
   `aws_secret_key` kwargs → the `aws_id` profile in
   `parrot.conf::AWS_CREDENTIALS` → the plain boto3 credential chain (env
   vars, shared credentials file, SSO, instance role, ...). Used by the
   adversarial and mechanical seats' Converse calls.
2. **Bedrock API key (bearer token)** — `AWS_NOVA_API_KEY` (conf), the
   same key `BedrockConverseBase` already uses. The `nova` dev seat's
   `bedrock-mantle` client uses **only** this path (a bearer token, not a
   SigV4 keypair) — see `NovaCodeDispatcher._resolve_bedrock_api_key()`.
   Missing it raises a clear `DispatchExecutionError` naming the key.

## Config keys (`conf.py`)

| Key | Default | Used by |
|---|---|---|
| `DEV_LOOP_NOVA_CODE_MODEL` | `minimax.minimax-m2.5` | dev seat (`build_dispatcher`'s `nova` branch) |
| `DEV_LOOP_NOVA_MANTLE_BASE_URL` | derived from region (below) | dev seat's `bedrock-mantle` client |
| `DEV_LOOP_NOVA_MANTLE_REGION` | `BEDROCK_AWS_REGION` → `AWS_REGION_NAME` → `us-east-1` | derives the mantle base URL when `DEV_LOOP_NOVA_MANTLE_BASE_URL` is unset: `https://bedrock-mantle.{region}.api.aws/v1` |
| `DEV_LOOP_NOVA_REVIEW_MODEL` | `us.amazon.nova-2-lite-v1:0` | adversarial seat |
| `DEV_LOOP_NOVA_MECHANICAL_MODEL` | `us.amazon.nova-2-lite-v1:0` | mechanical seat (PR enrichment) |
| `DEV_LOOP_ADVERSARIAL_BACKEND` | `codex` | adversarial-seat selector — `codex` or `nova` |
| `AWS_NOVA_API_KEY` | unset | Bedrock API key (bearer) — required for the dev seat, also usable for Converse |

## PR-body enrichment (mechanical seat)

`FeatureHandoffNode`/`DeploymentHandoffNode` splice an optional
`## Summary of changes` section into the PR body, generated by one
no-tools Converse call on `DEV_LOOP_NOVA_MECHANICAL_MODEL`. **Enrich,
never replace**: the deterministic template (`_build_title`/`_build_body`)
is untouched and is also the exact fallback — any LLM failure, timeout, or
empty response degrades silently to the pre-FEAT-405 template output.
Titles are never touched by the mechanical seat.

A *permanent* Bedrock condition (model not enabled for the account/region,
Anthropic use-case form not submitted, bad model id) logs one actionable
`WARNING` naming the model and the remedy — no stack trace, because the
fallback is the designed behaviour. Genuinely unexpected failures still log
with a full traceback.

## Per-agent usage report

Every dev-loop run now also writes `{run_id}.usage.json` and
`{run_id}.usage.html` alongside the existing `{run_id}.bundle.json` /
`{run_id}.report.md` (under `conf.OUTPUT_DIR/dev_loop_runs/`), and folds a
`## Usage` markdown section into `report.md`. All three views
(`usage.json`, the markdown section, `usage.html`) render from the same
`UsageReport` model, so they cannot disagree. Unreported values render
`—` (never a fabricated `0`), and no pricing/cost figure appears anywhere.

**Known limitation**: `UsageReport.agents` is keyed by dev-loop **node**
id (`"development"`, `"qa"`, ...), not by individual `DevAgentPool`
worker — `session_state.NodeId` is a closed `Literal` of the flow's fixed
node names, so a pool worker's own id (`"development.w1"`,
`"development.w2"`, ...) cannot be represented in session state today. A
future feature would need to widen that type (or add a separate
per-worker channel) to report per-worker usage for multi-worker pools.

## FEAT-404 soft dependency

FEAT-405 emits round-events for **every** dev-loop backend
(`ClientRoundEvent`, from `LLMCodeDispatcher`'s tool loop), but per-round
**accumulation** inside `BedrockConverseBase` (i.e. the Converse-based
adversarial and mechanical seats) is FEAT-404's job, shipped separately.

Until FEAT-404 lands: a Bedrock-backed seat's `rounds`/tokens render `—`
in the usage report — this is expected, not a bug. `nova` dev-seat rounds
(via `bedrock-mantle`, driven through `LLMCodeDispatcher`'s loop) are
unaffected and populate normally today.
