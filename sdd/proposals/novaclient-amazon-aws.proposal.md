---
id: FEAT-315
title: Unified NovaClient for all Amazon Nova models (text, voice, image, video)
slug: novaclient-amazon-aws
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-07-17
  summary_oneline: Refactor NovaSonicClient into a unified NovaClient covering all Amazon Nova models (text, voice, image, video)
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-315/
created: 2026-07-17
updated: 2026-07-17
---

# FEAT-315 — Unified NovaClient for all Amazon Nova models

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-315/`](../state/FEAT-315/)

---

## 0. Origin

The original request, preserved verbatim (Spanish). Full source at
`sdd/state/FEAT-315/source.md`.

> Actualmente se creó un cliente llamado `NovaSonicClient` con fallback a Nova
> text en algunos casos, la idea es hacer un refactor al estilo del cliente de
> google `parrot/clients/google/client.py` y llamarlo NovaClient, para la
> cobertura de todos los modelos Nova, como Nova 2 lite, Sonic, premier, micro
> o Pro, nova Reel, Nova Canvas al igual que google podrían ir a
> `parrot/clients/nova/generation.py` y así permitir que un único cliente se
> use para distintos modos y no tener múltiples clientes separados, con los
> métodos de stream voice en `parrot/clients/nova/audio.py` documentados en la
> API `InvokeModelWithBidirectionalStream`, mientras que los métodos `ask()`,
> `ask_stream()` o `invoke()` en `parrot/clients/nova/client.py` cubriendo los
> modelos nova 2 lite, micro y premier. Para conexión pide las credenciales o
> usa desde `parrot.conf` la variable `AWS_CREDENTIALS` con un `aws_id`
> (tal como Bedrock client).

**Initial signals** (extracted, not interpreted):
- Verbs: "hacer un refactor", "permitir que un único cliente" → refactor/unification, not a bug
- Named entities: `NovaSonicClient`, `NovaClient`, Nova 2 Lite / Sonic / Premier / Micro / Pro / Reel / Canvas, `AWS_CREDENTIALS`, `aws_id`, `InvokeModelWithBidirectionalStream`
- Reference architecture explicitly named: `parrot/clients/google/client.py`
- Acceptance criteria provided: no (structure prescription only)

---

## 1. Synthesis Summary

Refactor the experimental `NovaSonicClient`
(`packages/ai-parrot/src/parrot/clients/nova_sonic.py` — voice-only, with
text-by-delegation to `BedrockConverseClient`) into a unified **NovaClient**
subpackage at `packages/ai-parrot/src/parrot/clients/nova/`, mirroring the
`GoogleGenAIClient` architecture (`google/client.py` + capability mixins in
`google/generation.py`): `nova/client.py` carries `ask()`/`ask_stream()`/
`invoke()` over the Bedrock Converse API for the Nova text tiers
(2 Lite, Micro, Pro, Premier), `nova/audio.py` carries the Nova Sonic
bidirectional `stream_voice()` (ported from `nova_sonic.py`), and
`nova/generation.py` covers Nova Canvas (image) and Nova Reel (video).
Credentials resolve via an `aws_id` profile in `parrot.conf::AWS_CREDENTIALS`
— fixing the key-name bug in the current `bedrock.py` `aws_id` branch — with
explicit-kwarg and env fallbacks. The `'nova'` provider key is registered in
`factory.py::SUPPORTED_CLIENTS`; all `nova_sonic` call sites (`bots/voice.py`,
`ai-parrot-integrations`, tests) are migrated in-feature and
`nova_sonic.py` is deleted. Recommendation: proceed to `/sdd-spec FEAT-315`.

**Note on paths**: the repo is a monorepo — the user's requested paths
(`parrot/clients/nova/...`) resolve to
`packages/ai-parrot/src/parrot/clients/nova/...` (F001).

---

## 2. Codebase Findings

> Grounded in `sdd/state/FEAT-315/findings/`. Each entry cites finding IDs.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/clients/nova_sonic.py` | `NovaSonicClient` | 42–519 | refactor source: `stream_voice` + sender/receiver → `nova/audio.py`; text delegation replaced | F002 |
| 2 | `packages/ai-parrot/src/parrot/clients/google/client.py` | `GoogleGenAIClient` | — | reference: `AbstractClient` + capability mixins, lazy SDK guard, per-loop client cache | F003 |
| 3 | `packages/ai-parrot/src/parrot/clients/google/generation.py` | `GoogleGeneration` | — | reference mixin shape for image/video methods → Canvas/Reel | F003 |
| 4 | `packages/ai-parrot/src/parrot/clients/bedrock.py` | `BedrockConverseClient` | 62–140 | Converse text engine (already serves Nova text models) + `aws_id` precedent (buggy, see §2.2) | F004 |
| 5 | `packages/ai-parrot/src/parrot/conf.py` | `AWS_CREDENTIALS` | 490–531 | credential profiles keyed by `aws_id`; keys `aws_key`/`aws_secret`/`region_name` | F005 |
| 6 | `packages/ai-parrot/src/parrot/models/bedrock_models.py` | `PUBLIC_TO_BEDROCK` | 38–76 | model-ID translation map — missing `nova-premier`, `nova-canvas`, `nova-reel` | F006 |
| 7 | `packages/ai-parrot/src/parrot/clients/factory.py` | `SUPPORTED_CLIENTS` | 65–94 | register `'nova'` via the lazy-loader pattern | F007 |
| 8 | `packages/ai-parrot/src/parrot/bots/voice.py` | provider `'nova_sonic'` | 164–225 | call site to migrate to NovaClient | F008 |
| 9 | `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | `NovaSonicClient` import | 77, 98, 332 | cross-distribution call site to migrate | F008 |
| 10 | `packages/ai-parrot/src/parrot/interfaces/aws.py` | credential resolver | 46–56 | canonical `AWS_CREDENTIALS` resolver (correct keys, `'default'` fallback) | F004, F005 |

### 2.2 Constraints Discovered

- **AbstractClient contract.** NovaClient must implement `get_client()`,
  `ask()`, `ask_stream()`, `resume()`, `invoke()`
  (`clients/base.py:845,1525,1563,1592,1614`).
  *Evidence*: F009

- **Pre-Alpha voice SDK.** `InvokeModelWithBidirectionalStream` is only
  supported by `aws_sdk_bedrock_runtime==0.7.0` (Pre-Alpha, Python ≥ 3.12);
  boto3/aioboto3 cannot do it. The thin-wrapper isolation
  (`_open_stream`/`_send_event`/`_iter_events`) and the eager ImportError
  guard must be preserved in `nova/audio.py`.
  *Evidence*: F002

- **⚠ Latent credential bug (must fix in-feature).** The `aws_id` branch in
  `bedrock.py:109-120` (added by wip commit `3672eb2f4`) reads
  `access_key`/`secret_key`/`session_token`/`region`, but `AWS_CREDENTIALS`
  profiles define `aws_key`/`aws_secret`/`region_name` — the lookup always
  yields `None`. Worse, when the `aws_id` is not found, the credential
  attributes are never assigned → `AttributeError` at `get_client()` time.
  `interfaces/aws.py:46-56` shows the correct resolver (right keys +
  `'default'` fallback). NovaClient must use the correct keys, and the
  shared resolution should be extracted or fixed for both clients.
  *Evidence*: F004, F005

- **Voice response contract.** `stream_voice()` must keep yielding
  `LiveVoiceResponse` (from `clients/live.py`) including the 8-minute
  `reconnect_required` convention, so `VoiceChatHandler` and the
  integrations voice package keep working unchanged.
  *Evidence*: F002, F008

- **Cross-distribution blast radius.** `ai-parrot-integrations` is a separate
  distribution importing `parrot.clients.nova_sonic` directly
  (`voice/handler.py`, `voice/models.py::VoiceProvider.NOVA_SONIC`), and 5+
  test files pin the current module path. Since U2 resolved to *migrate
  everything now*, all of these move in this feature — the spec must
  enumerate them as explicit tasks.
  *Evidence*: F008

- **Subpackage export style.** `google/__init__.py` exports the client plus a
  friendly alias (`GoogleClient = GoogleGenAIClient`); `nova/__init__.py`
  should mirror this (`NovaClient` + exports).
  *Evidence*: F003

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `3672eb2f4` | 2026-07-17 | Jesus | wip: nova model — adds `aws_id` kwarg + `nova-2-lite` map entry | `clients/bedrock.py`, `models/bedrock_models.py` |
| `36bf8c57e` | recent | — | fix: NovaSonicClient base64 audio wire format | `clients/nova_sonic.py` |
| `e34e59600` | recent | — | feat: TASK-1748 NovaSonicClient (FEAT-302, Module 7) | `clients/nova_sonic.py` |

The `wip: nova model` commit shows FEAT-315's credential story is already
in flight; this proposal formalizes and fixes it. *Evidence*: F009, F006

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`packages/ai-parrot/src/parrot/clients/nova/__init__.py`** — exports
  `NovaClient` (+ back-compat names as needed), mirroring `google/__init__.py`.
- **`packages/ai-parrot/src/parrot/clients/nova/client.py`** — `NovaClient`
  core: `ask()`/`ask_stream()`/`invoke()`/`resume()`/`get_client()` over the
  Bedrock Converse API for Nova 2 Lite, Micro, Pro, Premier; `aws_id`-first
  credential resolution; default model `nova-2-lite`.
- **`packages/ai-parrot/src/parrot/clients/nova/audio.py`** — `NovaAudio`
  capability mixin: `stream_voice()` + `_audio_sender()` + the three thin
  Pre-Alpha SDK wrappers, ported from `nova_sonic.py` with the same event
  protocol, `LiveVoiceResponse` shape, and 8-minute reconnect signal.
- **`packages/ai-parrot/src/parrot/clients/nova/generation.py`** —
  `NovaGeneration` capability mixin, minimal parity with `GoogleGeneration`
  naming: `generate_image()` (Nova Canvas), `video_generation()` (Nova Reel).

### What Changes

- **`clients/bedrock.py`::`BedrockConverseClient.__init__`** — fix the
  `aws_id` credential-key mismatch and the unbound-attribute path (share the
  resolver with NovaClient; `interfaces/aws.py` is the reference).
  BedrockConverseClient **stays** for non-Nova Bedrock families (U1 follow-up:
  "keep both"); the shared Converse engine is refactored so both clients use
  it (e.g. a common base or extracted module). *Evidence*: F004
- **`models/bedrock_models.py`::`PUBLIC_TO_BEDROCK`** — add `nova-premier`,
  `nova-canvas`, `nova-reel` (+ any missing Nova 2 tiers); exact Bedrock IDs
  verified against AWS docs during spec (low-confidence today, C6/C7).
  *Evidence*: F006
- **`clients/factory.py`::`SUPPORTED_CLIENTS`** — add `'nova'` via a lazy
  loader (pattern: `_lazy_bedrock_converse`). *Evidence*: F007
- **`bots/voice.py`** — provider `'nova_sonic'` resolution now imports
  `NovaClient` from `parrot.clients.nova`. *Evidence*: F008
- **`packages/ai-parrot-integrations/src/parrot/voice/{handler,models}.py`**
  — migrate imports to `parrot.clients.nova`. *Evidence*: F008
- **Tests** — `tests/clients/test_nova_sonic.py`,
  `tests/bots/test_voicebot_nova_sonic_wiring.py`,
  `tests/models/test_voice_config.py`, `tests/models/test_bedrock_models.py`,
  integrations `tests/voice/test_nova_sonic_provider.py` — updated to the new
  module path/class. *Evidence*: F008
- **Deleted**: `clients/nova_sonic.py` (U2: migrate everything now, no shim).

### What's Untouched (Non-Goals)

- `AnthropicClient`'s Bedrock backend (`'bedrock'`/`'anthropic-aws'` factory
  keys, FEAT-232) — unrelated transport.
- `GoogleGenAIClient` and its mixins — reference only.
- Batch generation, reel assembly, music, speech-synthesis parity with
  `GoogleGeneration` (U4: minimal parity; defer).
- `parrot.conf::AWS_CREDENTIALS` schema — consumed as-is, not redesigned.

### Patterns to Follow

- Subpackage + capability mixins:
  `GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis)` →
  `NovaClient(..., NovaAudio, NovaGeneration)`. *Evidence*: F003
- Lazy SDK guard: module import never fails when the optional SDK is missing;
  instantiation raises an actionable ImportError. *Evidence*: F003, F002
- Thin SDK wrappers isolating unstable APIs
  (`_sdk_create`/`_sdk_stream`, `_open_stream`/`_send_event`/`_iter_events`).
  *Evidence*: F004, F002
- Factory lazy loaders for optional-dependency clients
  (`_lazy_bedrock_converse`). *Evidence*: F007
- Model translation through `bedrock_models.translate()` with
  `region_prefix` support. *Evidence*: F006

### Integration Risks

- **Cross-distribution coordination**: `ai-parrot-integrations` ships
  separately; deleting `parrot.clients.nova_sonic` without releasing both
  packages together breaks installed combinations. Mitigation: land both
  changes in the same PR train and release in lockstep (or reconsider a
  one-release shim at spec time). *Evidence*: F008
- **Converse-engine refactor regression**: extracting/sharing the text engine
  between BedrockConverseClient and NovaClient touches the well-tested
  bedrock suite (`test_bedrock_*.py`). Mitigation: keep
  BedrockConverseClient's public surface byte-identical; run the full suite.
  *Evidence*: F004, F008
- **MRO/composition pitfalls**: `AbstractClient.__init__` is known to shadow
  class attributes (the `_fallback_model` workaround in `bedrock.py`);
  the mixin composition must be checked against this. *Evidence*: F004
- **Unverified Canvas/Reel API shapes**: no in-repo precedent; Reel is an
  async job API (start/poll) unlike Canvas's synchronous `invoke_model`.
  Verify against AWS docs during spec (C6). *Evidence*: — (external)

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Target layout `nova/{client,audio,generation,__init__}.py` mirrors `google/` | F003 | high | directly cited reference architecture |
| C2 | Voice code ports to `audio.py` with no protocol changes | F002 | high | full read of `stream_voice` + wire protocol |
| C3 | Text modes ride the Converse API already proven by `BedrockConverseClient` | F004 | high | wiki page + read; Nova text already supported |
| C4 | Credential resolution via `aws_id`/`AWS_CREDENTIALS` needs the key-name fix | F004, F005 | high | direct read of both sides of the mismatch |
| C5 | Model map + factory additions are small, bounded edits | F006, F007 | high | direct reads |
| C6 | Canvas uses `invoke_model`; Reel uses `start_async_invoke` job polling | — | low | external AWS knowledge; no in-repo code to cite — verify during spec |
| C7 | Exact Bedrock IDs for `nova-premier`/`canvas`/`reel` (+ Nova 2 tiers beyond lite/sonic) | F006 | low | absent from the map; verify against AWS docs during spec |

Distribution: **5** high, **0** medium, **2** low.
(The two low-confidence claims affect spec details, not the architecture.)

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1: How should NovaClient implement the text methods?** —
  *Resolved*: "Migrate BedrockConverseClient into new NovaClient, NovaClient
  will be the unique client for multi-modal (like any others, one LLM model
  covering all features)"; follow-up clarified **keep both** — the shared
  Converse engine is refactored so NovaClient owns its text path while
  `BedrockConverseClient` survives for non-Nova Bedrock families.
  *Resolves claims*: C3
- [x] **U2: Fate of `parrot.clients.nova_sonic` and the `'nova_sonic'` key?**
  — *Resolved*: **migrate everything now** — update `bots/voice.py`,
  `ai-parrot-integrations`, and all tests in this feature; delete
  `nova_sonic.py`. *Resolves claims*: blast-radius constraint (§2.2)
- [x] **U3: Factory key and default model?** — *Resolved*: key **`'nova'`**,
  default **`nova-2-lite`** (`amazon.nova-2-lite-v1:0`), lazy-loader
  registration. *Resolves claims*: C5
- [x] **U4: Scope of `nova/generation.py`?** — *Resolved*: **minimal parity**
  — `generate_image()` (Canvas) + `video_generation()` (Reel), mirroring
  `GoogleGeneration` method names; batch/reel-assembly deferred.

### Unresolved (defer to spec / implementation)

- [ ] **Exact Bedrock model IDs and invocation shapes for Nova Premier,
  Canvas, Reel (and Nova 2 Pro/Micro/Premier tiers, if published)** —
  *Owner*: spec author. *Blocks claims*: C6, C7.
  *Plausible answers*: a) `us.amazon.nova-premier-v1:0` (inference-profile
  only), `amazon.nova-canvas-v1:0`, `amazon.nova-reel-v1:1` · b) newer Nova 2
  generation IDs — check the AWS model catalog at spec time.
- [ ] **Shape of the shared Converse engine** (common base class vs extracted
  module used by both `BedrockConverseClient` and `NovaClient`) — *Owner*:
  spec author. *Blocks claims*: —. *Plausible answers*: a) `ConverseEngine`
  mixin/base in `clients/bedrock.py` · b) new `clients/_converse.py` module.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-315`** — *Rationale*: localization is fully verified
(C1–C5 high), the reference architecture exists in-repo, all four design
unknowns are resolved, and the only open items are AWS-docs verifications
(C6, C7) that belong in the spec's Codebase Contract section.

### Alternatives

- **`/sdd-brainstorm FEAT-315`** — only if the shared-Converse-engine shape
  (§5 unresolved #2) deserves a multi-option architectural exploration.
- **`/sdd-task FEAT-315`** — not recommended; this is a multi-file,
  cross-distribution refactor, not a trivial localized fix.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-315/state.json` |
| Source (raw) | `sdd/state/FEAT-315/source.md` |
| Research plan | `sdd/state/FEAT-315/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-315/findings/F001-*.md` … `F009-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-315/synthesis.json` |

**Budget consumed** (profile: default):
- Files read: 9 / 40
- Grep calls: 8 / 25
- Git calls: 3 / 10
- Wiki calls: 5 (free)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (refactor request
with prescribed structure; no failure symptom to investigate).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus (jlara@trocglobal.com) + Claude (Fable 5) |
