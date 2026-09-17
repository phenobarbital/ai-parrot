---
id: FEAT-564
title: Reliable video reels with Gemini Omni and Veo 3.1
slug: video-reel-omni-veo-reliability
type: feature
mode: enrichment
status: review
source:
  kind: inline
  fetched_at: 2026-09-17
  summary_oneline: Repair video reel generation and add Gemini Omni alongside Veo 3.1.
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-564/
created: 2026-09-17
updated: 2026-09-17
---

# FEAT-564 — Reliable video reels with Gemini Omni and Veo 3.1

## 0. Origin

Requested: use gemini-omni-1.1-flash together with supported Veo 3.1, and turn the existing review into a proposal and specification for fixes and new model support. The exact input and full review snapshot are in [source.md](../state/FEAT-564/source.md) and [review-source.md](../state/FEAT-564/review-source.md).

This is a proposed design, not recorded user acceptance. Formal FEAT-564 was reserved through the ledger; the research identity is aligned with it.

Revision input: the user's Google Gemini review, preserved in [gemini-review-source.md](../state/FEAT-564/gemini-review-source.md). This revision verifies its six findings and five suggested changes, retaining the original Omni and reliability scope. Provider claims are qualified by API surface and evidence; the supplied review is not itself a compatibility certification.

## 1. Synthesis Summary

Keep the current HTTP job surface and shared reel assembly, introduce explicit director/image/video model selection, and dispatch video generation to separate Veo and Omni adapters [F001,F002,F009]. Replace the two-ID capability check with an API-specific registry; separate edit targets from generated durations, define audio/music failure policies, normalize provider errors, and restore meaningful handler coverage [F009–F012]. Retain Omni through asynchronous Interactions and the original upload, storage, artifact and lifecycle repairs [F003–F006]. Preserve Veo as the default family with per-scene overrides, but resolve concrete IDs against the configured API rather than assuming preview and GA IDs are interchangeable [F010]. Overall confidence remains medium because live account access, Omni output behavior and some deployment contracts have not been exercised.

## 2. Codebase Findings

### 2.1 Localization

Paths are repository-relative. Evidence files are under the research state findings directory.

| Path | Symbols / lines | Role | Evidence |
|---|---|---|---|
| packages/ai-parrot-server/src/parrot/handlers/video_reel.py | VideoReelHandler:119–335 | Upload, enqueue, poll, result delivery | F001 |
| packages/ai-parrot/src/parrot/models/google.py | VideoReelScene / VideoReelRequest:376–453 | Additive request contracts | F001 |
| packages/ai-parrot-client-google/src/parrot/clients/google/generation.py | video_generation:844; generate_video_reel:1905; _process_scene:2084; _generate_reel_music:2249; _create_reel_assembly:2308 | Routing, generation and assembly | F002 |
| packages/ai-parrot-client-google/src/parrot/clients/google/models.py | GoogleModel:41–69 | Provider model catalog | F002 |
| packages/ai-parrot-client-google/src/parrot/clients/google/client.py | get_client:630; close:693 | SDK resource ownership | F004 |
| packages/ai-parrot/src/parrot/models/responses.py | AIMessage.files:91; metadata:152; artifacts:155 | Preserve URL strings without widening Path fields | F003 |
| packages/ai-parrot-server/src/parrot/handlers/jobs/job.py | execute_job:209; _run_job:229 | Existing asynchronous execution | F004 |
| packages/ai-parrot-client-google/pyproject.toml | dependency:17 | Tested SDK floor | F006 |
| packages/ai-parrot/tests/test_video_reel_handler.py | handler fixture:70–90 | Reproduced read-only request failure | F012 |

### 2.2 Constraints

- Async provider I/O, Pydantic v2 and satellite ownership remain binding; core request models cannot import provider enums [F007].
- Preserve existing POST 202 and polling behavior, augment JSON schema, keep provider imports lazy [F001].
- Keep AIMessage.files for actual local paths; add typed reel descriptors in existing metadata/artifacts [F003].
- Resolve SDK resource ownership in Google generation code. The shared base client is a verified dependency, not an authorized broad refactor [F004].
- Prior tests do not establish an end-to-end pass: 42 passed, 3 storage-stub failures, 20 fixture errors, 1 skipped [F003].
- Fresh focused handler baseline: 13 passed, 20 setup errors, 8 warnings. These results do not replace the prior broader baseline [F012].
- Installed SDK is 2.23.0; neither the declared minimum 2.18.1 nor the review's 2.24.0 is certified by this revision [F006,F010].

### 2.3 Recent History

Provider extraction on 2026-09-04 (7f7f6f165, a0471ded2, 77b599141), formatting on 2026-09-05 (14b548483), and handler satellite move on 2026-05-29 (434423d45) explain current locations. No defect causality is inferred solely from history [F007].

### 2.4 Disposition of Gemini's findings

| Gemini finding | Verified disposition | Design consequence |
|---|---|---|
| Hardcoded Veo and narrow detection | Confirmed: only two enum values receive Veo 3.1 options [F009]. GA migration is documented for Vertex, while the Gemini guide still uses preview IDs [F010]. | Explicit model routing and registry keyed by API surface plus exact ID; reject unknown combinations. Do not use `"veo-3" in model_str` to grant capabilities. |
| SDK 2.24.0 / missing generate_audio | Version claim does not match this environment. The field already exists in 2.23.0, but Developer API serialization rejects it [F010]. | Test actual transport conversion; distinguish provider generation controls from local soundtrack retention. |
| HTTP model has no effect | Confirmed for director and video selection; image generation also selects its own default. “Zero effect” is too broad because client model can influence SDK location/version [F009]. | Explicit stage parameters, deterministic legacy alias behavior, and observable effective models. |
| Every scene is eight seconds | Eight seconds is requested, and assembly does not trim. Exact returned/final durations were not measured; unconditional “four scenes always equal 32s” is overstated [F009]. | Supported generation duration covering the edit target; inspect and trim actual media, then compute the final timeline. |
| Lyria is private / fails for almost everyone | Unsupported. Google publishes an experimental endpoint and connection example; deployed access remains unverified [F011]. | Optional dependency with visible failure policy, configurable supported API version, deadline and capability checks. |
| Safety exception handling is narrow | Confirmed; immediate SDK errors bypass the RuntimeError substring branch. ClientError is already an APIError subclass [F009,F010]. | Classify immediate errors, terminal operation errors and filtered output consistently; remove the altered-input safety retry. |
| Handler tests fail at fixture setup | Reproduced, with 13 other tests passing [F012]. | Use real view initialization where practical; assigning `_request` is the minimum repair, not sufficient evidence of HTTP correctness. |

Provider evidence: [Gemini Veo documentation](https://ai.google.dev/gemini-api/docs/veo), [Vertex migration notes](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes), and [Lyria RealTime documentation](https://ai.google.dev/gemini-api/docs/realtime-music-generation), checked 2026-09-17. SDK transport evidence is recorded in F010.

## 3. Probable Scope

### New capability

Propose video_model at reel level (default Veo 3.1 standard for the configured API), with nullable scene-level video_model overrides. Initial Gemini Developer API selections are Veo 3.1 standard/Fast/Lite preview and gemini-omni-1.1-flash; Vertex defaults and supported IDs require separate registry entries and transport tests [F005,F008,F010]. A reel may assemble clips from both API families where deployment access supports them. This is local clip composition, not uploading a Veo clip to Omni for editing [F002,F005]. Veo 2 is not automatically added to the reel's supported set; preserve its existing public video-generation behavior and require an independently verified capability profile before enabling it here.

Use an internal normalized generated-clip record, separate backend adapters, and a capability registry. The Omni adapter uses public c.aio.interactions APIs, handles inline/URI output, and emits the same local clip contract as Veo. It must not reuse the synchronous deep-research loop [F006]. New names and modules below are proposed, not asserted as existing.

### Review-to-requirement mapping

| Review item | Required change | Evidence |
|---|---|---|
| 1: Veo parameter mismatch | Lowercase values; modality/region capability checks; no safety-filter bypass retries | F002,F008 |
| 2: corrupt URLs | Artifact descriptors with string URLs, safe local HTTP delivery and signed-cloud URL refresh | F003 |
| 3: music encoding | Explicit PCM format, correct WAV metadata/extension, no speech-helper regression | F003 |
| 4: model/duration | Effective scene model, separate target vs generated duration, capability validation | F001,F002 |
| 5: upload correspondence | Stable indices, unique filenames and sparse-slot preservation | F001,F003 |
| 6: validation/cleanup | Mapping validation, multipart JSON fields, bounded uploads, cleanup every exit | F001,F003 |
| 7: SDK lifetime | Explicit owned sessions and per-version clients; deterministic cleanup | F004 |
| 8: job reliability | Deadlines, cancellation, bounded safe retries, explicit partial-result policy | F002,F004 |
| 9: assembly | Actual overlap, WebM-compatible audio, narration timing, isolated job directories | F002,F003 |
| 10: trust boundary | Verify caller ownership and allowed storage roots; reject arbitrary HTTP paths | F001,F003 |
| 11: polling | Support both query and route job IDs; define conflicting-ID response | F001 |
| Tests | Repair real fixtures; boundary and media tests; optional live smoke suite | F003,F006 |

### Proposed policy decisions

- Treat legacy top-level model as a deprecated director-model alias, never as video_model. This repairs a previously ineffective stage selector; document the behavior change and precedence below [F009].
- Scene duration is an edit target. Request a supported Veo duration covering it and trim locally. Omni initially uses provider-default generation length and trims when possible; no invented duration enum. Fail clearly if actual output is too short.
- Preserve separate narration/music as the default audio mode and mute model audio. Add an explicit native-audio mode; reject simultaneous separate narration/music settings until mixing is deliberately supported.
- Default partial_failure_policy=fail; opt-in skip yields per-scene errors and a partial marker.
- No cross-model automatic fallback, safety-block resubmission, multi-turn editing, video extension or UI overhaul in this scope.
- Use owned SDK clients with deadlines. Retrying reads/downloads is distinct from resubmitting a billable generation request after an ambiguous timeout.
- Keep native URI fetching behind an adapter boundary with authenticated Google-origin requests or signed downloads; do not forward credentials to arbitrary redirect hosts.

These are recommendations for review, not answers attributed to the user.

### 3.1 Stage routing and request contract

All fields below are proposed additions, with validation shared by HTTP and direct Python callers. Core models use strings and literals; the provider satellite owns capability resolution [F007,F009].

| Field | Proposed default / resolution | Required behavior |
|---|---|---|
| video_model | Omitted: API-specific Veo 3.1 standard default | Effective scene override → reel selection → backend default. Explicit IDs are never silently rewritten across APIs. |
| scenes[].video_model | null: inherit | Validate every effective model before scene generation. |
| director_model | Omitted: explicit legacy model, otherwise gemini-2.5-flash | Forward to scene breakdown. Preserve the actual current director default, not the handler's unused gemini-3.5-flash default [F009]. |
| image_model | gemini-3.1-flash-image-preview | Forward explicitly to both background and foreground generation, subject to deployment capability validation [F009]. |
| resolution | 720p | Validate against every selected video profile; canonical values 720p, 1080p, 4k. Never silently drop an explicit resolution. |
| audio_mode | separate | Enum: separate, native, muted. |
| music_policy | optional in separate mode | Enum: off, optional, required. Native/muted skip music; reject conflicting explicit music controls. |
| partial_failure_policy | fail | Optional skip retains scene order, errors and an explicit partial marker. All scenes failed is always failure. |

If both legacy model and director_model are supplied and differ, return validation error; identical values are accepted with a deprecation warning. Explicitly supplied invalid/null/empty model values must not turn into silent defaults; only the scene override uses null for inheritance. When scenes are supplied, the director is unused and metadata says so. Configure provider clients using each effective stage model, so self.model cannot silently select the wrong location/API version. Report requested and effective models, API surface and relevant version in job metadata without credentials [F009,F010].

Capability records must describe exact model/API, supported input modes, durations, resolutions, audio controls, person-generation constraints and source/check date. A registered future GA ID can be added centrally with contract tests without changing orchestration. Unknown IDs produce actionable validation errors. Lite must not inherit standard/Fast reference-guidance or 4k support. Existing `reference_image` is a starting frame; provider `reference_images` is asset guidance and has different constraints [F009,F010]. Region policy comes from deployment configuration, not guesses from model strings or the caller's timezone.

| API surface | Concrete model IDs to profile | Admission rule |
|---|---|---|
| Gemini Developer API / Veo | veo-3.1-generate-preview, veo-3.1-fast-generate-preview, veo-3.1-lite-generate-preview | Separate capability entries and transport tests [F008,F010]. |
| Vertex / Veo | veo-3.1-generate-001, veo-3.1-fast-generate-001 | Enable only with verified Vertex capabilities and credentials; never alias onto Developer API [F010]. |
| Gemini / Omni Interactions | gemini-omni-1.1-flash | Separate adapter with verified access and output contract [F005,F006]. |
| Veo 2 | veo-2.0-generate-001 | Existing public method compatibility is retained; reel admission deferred pending its own verified profile [F009,F010]. |

### 3.2 Timeline and narration

Use finite positive scene edit targets, initially bounded to eight seconds to avoid implicit splitting/extension. Keep the five-second default. Select the smallest permitted provider duration covering the target, then apply profile constraints; do not clamp the edit target itself. For a permitted 720p starting-frame request, five seconds selects six seconds; a profile requiring eight seconds selects eight. Pass the resolved duration explicitly and retain requested, submitted, measured and final durations [F009,F010].

Trim decoded clips to the edit target using the installed MoviePy API. If measured media is too short beyond one output-frame tolerance, return insufficient_duration; do not loop, stretch or submit another paid generation. Omni keeps provider-default duration until its duration contract is verified [F006]. Reject non-finite, zero, negative and out-of-range targets before generation. Validate director-produced scenes before starting image/video work.

For cuts, final duration is the sum of retained edit targets; for crossfades, subtract actual overlaps. Validate overlap against neighboring clip lengths and preserve original scene indices if skipping failures. Four five-second scenes therefore target 20 seconds with cuts or 18.5 seconds with three 0.5-second overlaps, within one output frame. These are proposed acceptance examples, not observed current outputs.

Narration is measured independently. Longer-than-target narration fails with narration_too_long; shorter narration does not extend the edit target. Silence for the remaining intended scene time is valid—three seconds of speech in a five-second scene does not imply a three-second edit. Preserve the existing speech-list precedence, document it, and do not silently time-stretch speech. Align background music to the final retained timeline, including transitions and skipped scenes [F009].

### 3.3 Audio and music dependency

Separate mode removes generated sound before attaching user narration and optional music. Native mode preserves model sound and rejects separate narration/music controls. Muted mode emits no soundtrack and skips TTS/music. Validate native-audio capability per backend; do not claim that local muting avoids provider audio generation or charges. Do not blindly send generate_audio to the Developer API; only use a provider-side switch when its transport and selected model support it [F010].

Music off makes no connection. Optional preserves current best-effort behavior, including a synthesized music prompt when none is supplied, but returns structured unavailable/timeout/failed status and a warning on failure. Required fails the job on missing, empty or failed music. Keep music_policy distinct from scene partial_failure_policy. Neither policy enables safety-filter retries [F009,F011].

Validate Lyria against the configured API/credentials and use an isolated owned client with a tested API version. The current public example uses v1beta while code forces v1alpha; do not assume either universal access or universal failure [F011]. Bound connect/receive time and bytes, propagate cancellation, and close the music session on every exit. Use verified PCM sample rate/channel/sample-width metadata and matching WAV content, MIME and extension; do not reuse speech encoding assumptions [F003,F011]. A new music provider is outside this proposal.

### 3.4 Error and retry contract

Normalize APIError (including ClientError), terminal operation errors, filtered/empty output, download failures and local media failures into structured stage/scene errors. Use provider status/reason fields where available; do not classify every 400/403 as safety or depend only on exception text. Distinguish safety_blocked, authentication/access failure, invalid configuration, quota/rate limit, timeout, insufficient_duration and provider_failure [F009,F010].

Safety blocks are terminal for that scene: no image removal, prompt rewriting or model switching. Apply fail/skip policy explicitly and surface the reason. Authentication and invalid-parameter failures are not retryable. Bound retries for documented transient failures on safe reads/downloads; generation resubmission after an ambiguous timeout requires proven idempotency/recovery, not a generic exception retry. Record operation IDs so polling can resume without duplicating paid work. Cancel and await concurrent tasks and complete cleanup before publishing terminal job state [F002,F004].

### 3.5 Verification and acceptance criteria

The following extend, rather than replace, the original upload/storage/lifecycle scope. Implementation must satisfy all rows; this proposal does not mark them passed.

| ID | Acceptance condition and evidence required |
|---|---|
| R01 | HTTP and direct callers select director, background/foreground image, reel video and scene video independently. Tests assert actual adapter call arguments, legacy alias conflicts and unused-director metadata. |
| R02 | Registry tests cover Developer API preview IDs, separately verified Vertex GA profiles, Lite exclusions, unknown IDs, wrong-API IDs and regional constraints; invalid combinations fail before paid scene calls. |
| R03 | Default five-second scene requests a legal covering duration and is trimmed. Test 4/5/6/8 targets, high-resolution constraints, starting frame versus asset guidance, non-finite inputs and too-short media. |
| R04 | Real small media fixtures verify cut/crossfade timeline and narration overflow within one frame; skipped scenes preserve correspondence and music follows final duration. |
| R05 | Separate/native/muted modes produce the specified soundtrack; unsupported generate_audio is absent from Developer API serialization. Music off avoids calls; optional warns; required fails; native/muted avoid TTS/Lyria. |
| R06 | Test SDK immediate safety error, operation safety failure and filtered output: each makes one generation attempt and preserves the structured reason. Auth/validation errors never enter transient retry paths. |
| R07 | Handler fixture uses valid request ownership and all 20 setup errors are eliminated. Exercise the queued job callback and effective model forwarding; merely replacing request assignment is insufficient. |
| R08 | Test Lyria handshake/access failure, timeout, empty stream, cancellation and valid PCM-to-WAV media; music version/client ownership is independent of director/video clients. |
| R09 | Preserve original artifact URL fidelity/access control, indexed uploads, JSON validation, quotas, cleanup, job polling, session closure and WebM codec tests [F001–F004]. |
| R10 | SDK matrix tests public async submission/poll/download and Omni output contracts on the chosen minimum and locked version. Documentation states tested versions; 2.24.0 support is claimed only after verification. |
| R11 | Opt-in live smoke tests record model/API/version/region and validate playable Veo, Omni and mixed reels, native sound and optional music outcomes. Access failures are reported separately from application failures. |

Default CI uses provider/cloud mocks plus real request, serialization, storage and small-media boundaries. Paid smoke tests are opt-in and were not run for this revision. Repair or migrate tests into the owning distributions during implementation; no fixture or application fix is included here [F007,F012].

## 4. Confidence Map

| Claim | Evidence | Confidence | Basis |
|---|---|---|---|
| Handler and scene orchestration are localized | F001,F002 | high | Source and wiki |
| Existing output/audio/upload defects are reproduced | F003 | high | Persisted probes |
| SDK 2.23.0 exposes async Omni transport/output fields | F006 | high | Offline introspection and installed source |
| Omni and Veo can normalize to a shared clip assembly contract | F002,F005,F006 | medium | Architecture inference; no live generation |
| Veo 3.1 remains available in the documented catalog | F008 | high | Official documentation |
| Live account/region access and Omni duration behavior | F005,F006 | low | Not exercised |
| Hardcoded stages and missing edit-duration propagation | F009 | high | Fresh source trace |
| SDK field presence does not imply Developer API audio support | F010 | high | Installed 2.23.0 transport source |
| Gemini preview and Vertex GA IDs need distinct profiles | F010 | high | Official API-specific documentation |
| Private-only Lyria claim is unsupported | F011 | high | Public experimental API documentation; no universal access claim |
| Handler fixture setup regression | F012 | high | Fresh focused run: 13 passed, 20 errors |

Overall: medium. Proposal/spec drafting is justified; implementation cannot claim live readiness without smoke verification.

## 5. Open Questions

Resolved through research: Omni requires a separate API adapter [F005,F006]; Veo remains the compatibility default [F008].

Design recommendations still awaiting proposal acceptance:
1. Reel defaults with scene overrides, and exclusions for automatic fallback/conversational editing.
2. Deprecated model → director_model alias, conflict rejection, and stage-specific defaults.
3. Music optional by default in separate mode, with explicit off/required alternatives.

Implementation evidence gates: verify Omni duration/URI authentication, deployed owner/tenant conventions, enabled model/API profiles and Lyria API version/PCM contract. These are engineering verification tasks, not requests for the user to guess API behavior. None prevents completing this proposal revision.

## 6. Recommended Next Step

Reconcile the existing [draft specification](../specs/video-reel-omni-veo-reliability.spec.md) with this revision before approval or task decomposition. In particular, add director/image routing, legacy alias conflict behavior, API-specific model profiles, music policy/status, SDK audio transport constraints and R01–R11. That draft predates this revision and is not updated or approved by this proposal-only request. No implementation tasks are created here.

## 7. Research Audit

- State: sdd/state/FEAT-564/state.json
- Source snapshots: source.md, review-source.md and gemini-review-source.md
- Research plan: research_plan.json
- Findings: findings/F001–F012; F009–F012 are this revision's verification
- Synthesis: synthesis.json
- No paid API generation or new dependency installation.
- Prior research budget retained in state. Revision reuses F001–F008 and adds source/SDK/docs verification plus one focused test run; no broad suite or live-provider pass is claimed. Fresh log: artifacts/logs/video_reel_proposal_revision_pytest.log.
- Template discrepancy: plan prompt requires wiki priority 0, but plan schema excludes wiki query types. Completed wiki orientation is recorded in extensible plan metadata; schema-valid read queries cover persisted evidence.

## 8. Provenance

sdd-proposal enrichment revision, informed by repository-wiki orientation and independent verification of the supplied Gemini review. Official sources checked 2026-09-17; installed SDK 2.23.0. Prior spec generation is historical; this turn revises proposal/research records only. Explicit user approval of draft policies remains pending.
