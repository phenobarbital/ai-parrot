---
type: Wiki Overview
title: FEAT-232 — Expand AnthropicClient to support AWS Bedrock and AWS-native backends
id: doc:sdd-proposals-enable-anthropic-aws-bedrock-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim. The full source is at
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

---
id: FEAT-232
title: Expand AnthropicClient to support AWS Bedrock and AWS-native (workspace) backends
slug: enable-anthropic-aws-bedrock
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-10
  summary_oneline: Expand AnthropicClient to support AWS Bedrock and AWS-native (workspace) backends
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-232/
created: 2026-06-10
updated: 2026-06-10
---

# FEAT-232 — Expand AnthropicClient to support AWS Bedrock and AWS-native backends

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-232/`](../state/FEAT-232/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at
`sdd/state/FEAT-232/source.md`.

> **AnthropicClient expansion** — La API nativa de Anthropic soporta usar AWS
> Bedrock y AWS Native:
>
> ```python
> from anthropic import AnthropicBedrock
> client = AnthropicBedrock(
>     aws_access_key="<access key>",
>     aws_secret_key="<secret key>",
>     aws_session_token="<session_token>",  # opcional, credenciales temporales
>     aws_region="us-east-1",               # por defecto lee AWS_REGION
> )
> ```
>
> ```python
> from anthropic import AnthropicAWS
> client = AnthropicAWS(api_key=os.environ["ANTHROPIC_API_KEY"], aws_workspace_id=, aws_region="us-east-1")
> ```
>
> Instalable via: `uv pip install -U "anthropic[aws]"`
>
> Con la diferencia de que el modelo en AnthropicAWS es de tipo sin prefijo
> ("claude-fable-5") y en Bedrock usa IDs de tipo ARN (habría que hacer una
> clase que convierta de uno en otro). Las credenciales deberían leerse primero
> desde parrot.conf, de ser nulas, se usan desde environment (ej:
> ANTHROPIC_API_KEY o ANTHROPIC_AWS_WORKSPACE_ID).

**Initial signals** (extracted, not interpreted):
- Verbs: "soporta", "leerse", "convierta" → feature/expansion, not a bug.
- Named entities: `AnthropicBedrock`, `AnthropicAWS`, `aws_workspace_id`, `ANTHROPIC_API_KEY`, `parrot.conf`.
- Components / labels: none (inline source).
- Acceptance criteria provided: no.

---

## 1. Synthesis Summary

The request is to let AI-Parrot's existing `AnthropicClient`
(`clients/claude.py`) reach Claude through **three** transports — the current
direct Anthropic API, **AWS Bedrock** (`AnthropicBedrock`), and **AWS-native /
workspace** (`AnthropicAWS`) — selected by a `backend=direct|bedrock|aws`
parameter. Because `get_client()` (`clients/claude.py:78`) is the *only* place
the SDK object is constructed and the rest of the ~1600-line completion pipeline
operates on whatever it returns, the change concentrates in a single seam:
`get_client()` becomes a small factory that builds a per-backend SDK client,
while a model-ID translation layer adapts public model IDs (e.g.
`claude-sonnet-4-6`) to Bedrock's prefixed/inference-profile IDs at the four
sites that resolve the model string. Credentials are read from `parrot.conf`
first (reusing the `AWS_ACCESS_KEY`/`AWS_REGION_NAME` constants pattern already
established in `interfaces/aws.py`), falling back to environment, then to the
SDK's own AWS chain. Recommendation: implement on top of the existing class via
a backend-strategy pattern and register the new transports in `LLMFactory`.

---

## 2. Codebase Findings

> All entries are grounded in the research findings persisted at
> `sdd/state/FEAT-232/findings/`. No fabricated paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/clients/claude.py` | `AnthropicClient.get_client` | 78-90 | **single** SDK-construction seam; lazy `from anthropic import AsyncAnthropic` | F001 |
| 2 | `packages/ai-parrot/src/parrot/clients/claude.py` | `AnthropicClient.__init__` | 62-76 | credential intake (`api_key or config.get('ANTHROPIC_API_KEY')`) | F001 |
| 3 | `packages/ai-parrot/src/parrot/clients/claude.py` | model resolution sites | 227, 499, 638, 662 | 4 sites resolving the model string → Bedrock translation seam | F004 |
| 4 | `packages/ai-parrot/src/parrot/clients/factory.py` | `SUPPORTED_CLIENTS` | 49-69 | provider registry; add `bedrock` / `anthropic-aws` keys | F002 |
| 5 | `packages/ai-parrot/src/parrot/clients/factory.py` | `_lazy_claude_agent` | 16-46 | precedent: lazy loader with actionable `pip install` hint | F002 |
| 6 | `packages/ai-parrot/src/parrot/interfaces/aws.py` | `AWSInterface` | 51-83 | reusable *parrot.conf → env → boto-chain* credential pattern | F003 |
| 7 | `packages/ai-parrot/src/parrot/models/claude.py` | `ClaudeModel` | 4-28 | public model IDs to map to Bedrock IDs | F004 |

### 2.2 Constraints Discovered

- **`get_client()` is the sole SDK seam.** Everything downstream
  (completion, streaming, vision, tool-calls, batch) consumes its return value
  via the base class's per-loop client cache. *Implication*: a backend switch
  belongs entirely inside `get_client()` + a model-translation hook; the
  completion logic stays untouched. *Evidence*: F001

- **Model string is resolved at 4 distinct call sites** (`:227`, `:499`,
  `:638`, `:662`). *Implication*: Bedrock ID translation must be applied at a
  shared chokepoint every site funnels through, or Bedrock calls will 404 on
  unprefixed IDs. This is the primary correctness risk. *Evidence*: F004

- **A parrot.conf → env → SDK-chain credential pattern already exists.**
  `interfaces/aws.py` reads `AWS_ACCESS_KEY`/`AWS_SECRET_KEY`/`AWS_REGION_NAME`
  from `parrot.conf` and *deliberately* lets the SDK fall through to the
  standard AWS chain (`~/.aws/credentials`, `AWS_ACCESS_KEY_ID`, IMDS) when no
  explicit profile is given — exactly the `AnthropicBedrock` no-keys behavior
  the source describes. *Implication*: reuse these constants instead of inventing
  new ones. *Evidence*: F003

- **New backends register by adding keys to `SUPPORTED_CLIENTS`**, ideally via
  the `_lazy_*` loader pattern so a missing optional dep fails with a clear hint
  rather than an import error at module load. *Evidence*: F002

### 2.3 Recent History (Relevant)

No `git_log` queries were run in this budget (the source is a greenfield
expansion, not a regression). The localization is verified by direct read, not
by recent-change correlation. Absence of recent churn on `claude.py`'s
`get_client()` reduces merge-risk for the change.

---

## 3. Probable Scope  *(mode = enrichment)*

### Decided Design (from §5 Q&A)

A **backend-strategy pattern on the existing single class**: keep one
`AnthropicClient` for all Claude communication; add a `backend` parameter
(`direct` | `bedrock` | `aws`, default `direct`). `get_client()` becomes a
factory that instantiates a small composable backend object — including the
current direct path — based on `backend`. Shared logic stays in
`AnthropicClient`; only credential intake, SDK selection, and model translation
vary per backend. **Both** Bedrock and AWS-workspace backends ship in this
feature.

### What's New

- **Backend abstraction** — small composable backend objects (e.g.
  `DirectBackend`, `BedrockBackend`, `AWSWorkspaceBackend`) each knowing how to
  (a) build their SDK client and (b) translate a public model ID. `get_client()`
  selects one by `self.backend`.
- **Bedrock model-ID translator** — `Map + region-prefix + pass-through`:
  a static `ClaudeModel → Bedrock base ID` map, a configurable cross-region
  inference-profile prefix (`us.` / `eu.` / `apac.`), and verbatim pass-through
  when the caller already supplies a Bedrock-formatted ID/ARN.
- **Factory keys** — `"bedrock"` and `"anthropic-aws"` (aliases TBD) in
  `SUPPORTED_CLIENTS`, mapping to `AnthropicClient` pre-bound to the right
  `backend` (or to thin lazy loaders).

### What Changes

- **`clients/claude.py`::`AnthropicClient.__init__`** — accept `backend` plus
  AWS credential kwargs (`aws_access_key`, `aws_secret_key`, `aws_session_token`,
  `aws_region`, `aws_workspace_id`); read each from `parrot.conf` first, then
  env, then leave `None` for the SDK chain. *Evidence*: F001, F003
- **`clients/claude.py`::`AnthropicClient.get_client`** — dispatch on `backend`
  to construct `AsyncAnthropic` / `AsyncAnthropicBedrock` / `AsyncAnthropicAWS`.
  *Evidence*: F001
- **`clients/claude.py` model-resolution sites (`:227/:499/:638/:662`)** — route
  the resolved model string through a `_translate_model()` chokepoint so Bedrock
  IDs are applied uniformly. *Evidence*: F004
- **`clients/factory.py`::`SUPPORTED_CLIENTS`** — add the two new provider keys.
  *Evidence*: F002
- **Packaging** — fold `anthropic[aws]` (+ boto if required) into the existing
  `[anthropic]` extra; keep lazy imports inside `get_client()`.

### What's Untouched (Non-Goals)

- The completion / streaming / vision / tool-call / batch logic in `claude.py`
  (operates on the SDK client unchanged).
- `AbstractClient`'s per-loop client cache machinery.
- Other providers (`gpt`, `groq`, `google`, …) and their factory entries.
- Anthropic Vertex (Google Cloud) backend — not requested.

### Patterns to Follow

- **Lazy SDK import + actionable hint** — mirror `_lazy_claude_agent`
  (`factory.py:16-46`) and the existing `get_client()` ImportError message. *Evidence*: F002, F001
- **parrot.conf → env → SDK-chain credentials** — mirror `AWSInterface`
  (`interfaces/aws.py:51-83`), including the deliberate fall-through. *Evidence*: F003

### Integration Risks

- **Incomplete model-translation coverage** — if any of the 4 resolution sites
  bypasses `_translate_model()`, Bedrock calls 404. *Mitigation*: funnel all
  sites through one helper; add a Bedrock-path unit test per site. *Evidence*: F004
- **AWS-workspace SDK shape unverified** — the `AnthropicAWS` / async variant
  and `aws_workspace_id` param name are the lowest-confidence claim in the
  source. *Mitigation*: verify `from anthropic import AsyncAnthropicAWS` (or the
  actual name) against the installed `anthropic[aws]` during implementation
  before wiring the factory key. *Evidence*: F004
- **Backend ≠ model-prefix surprises** — Bedrock inference-profile prefixes are
  region- and account-dependent; a hard-coded prefix can break cross-region
  callers. *Mitigation*: make the prefix configurable with pass-through escape hatch.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `get_client()` (`claude.py:78`) is the only SDK-construction point | F001 | high | direct read; all paths use base-class client cache |
| C2 | Subclass/strategy override of `get_client()` reuses the full completion pipeline | F001 | high | pipeline operates on the returned client only |
| C3 | Model string is resolved at 4 sites and all must route through translation | F004 | high | direct grep of `:227/:499/:638/:662` |
| C4 | Repo already has a parrot.conf→env→boto credential pattern to mirror | F003 | high | direct read of `interfaces/aws.py` + conf constants |
| C5 | New backends register via `SUPPORTED_CLIENTS` + lazy loader | F002 | high | direct read of `factory.py` |
| C6 | `AsyncAnthropicBedrock` shares the same `.messages` surface as `AsyncAnthropic` | F001 | medium | SDK convention; not exercised in repo |
| C7 | `AnthropicAWS`/`aws_workspace_id` exists with an async variant in `anthropic[aws]` | F004 | low | asserted by source only; not verified in repo or SDK |

Distribution: **5** high, **1** medium, **1** low.

> The single `low` claim (C7) is isolated to the AWS-workspace backend; it does
> not undermine the Bedrock path or the overall architecture. Bounded by it,
> overall confidence is **medium**.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Class topology — subclasses vs. backend switch?** — *Resolved*: one
  `AnthropicClient` with `backend=direct|bedrock|aws`; `get_client()` is the
  factory that instantiates a composable backend object (including the current
  direct SDK). Reduced shared code in the main class, single class for talking
  to Claude. *Resolves*: C2
- [x] **Bedrock model-ID translation strategy?** — *Resolved*: Map + region
  prefix + pass-through (all three). *Resolves*: C3
- [x] **AWS-workspace path in scope now?** — *Resolved*: yes — both backends in
  this feature; verify the `AnthropicAWS`/async class + `aws_workspace_id` param
  against the installed `anthropic[aws]` SDK during implementation. *Resolves*: C7 (partially — verification deferred to impl)
- [x] **Packaging?** — *Resolved*: fold `anthropic[aws]`/boto into the existing
  `[anthropic]` extra; keep lazy imports in `get_client()`.

### Unresolved (defer to spec / implementation)

- [ ] **Exact `AnthropicAWS` async class name + `aws_workspace_id` param** —
  *Owner*: implementer. *Blocks*: C7. *Plausible answers*: a) `AsyncAnthropicAWS`
  · b) `AnthropicAWS` only (sync) requiring a thread wrapper · c) different name
  in current SDK.
- [ ] **Factory key naming for the AWS-workspace backend** — `"anthropic-aws"`
  vs `"aws"` vs `"claude-aws"`. *Owner*: tbd.
- [ ] **Cross-region inference-profile prefix default** — ship `us.` as default
  or require explicit config? *Owner*: tbd.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-232`** — *Rationale*: localization is high-confidence
(C1–C5), the design forks are all resolved (§5), and the change is well-bounded
to `get_client()` + a model-translation chokepoint + factory wiring. The one
low-confidence item (C7, AWS-workspace SDK shape) is an implementation-time
verification, not an architectural unknown — it does not warrant a brainstorm.

### Alternatives

- **`/sdd-brainstorm FEAT-232`** — only if you want to reconsider the
  backend-strategy decision (e.g. separate subclasses) before specifying.
- **`/sdd-task FEAT-232`** — not recommended; this is multi-file (client,
  factory, model translator, packaging, tests), too large for a single task.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-232/state.json` |
| Source (raw) | `sdd/state/FEAT-232/source.md` |
| Findings (digests) | `sdd/state/FEAT-232/findings/F001…F004` |
| Synthesis (JSON) | `sdd/state/FEAT-232/synthesis.json` |

**Budget consumed** (profile: default):
- Files read: 7 / 40
- Grep calls: 8 / 25
- Git calls: 0 / 10
- Truncated: **no**

**Mode determination**: source provided a concrete design with SDK examples and
a credential strategy → resolved to `enrichment`.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal` |
| Source kind | inline |
| Operator | Jesus Lara |
