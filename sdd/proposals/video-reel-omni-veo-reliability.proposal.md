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

## 1. Synthesis Summary

Keep the current HTTP job surface and shared reel assembly, introduce explicit video-model selection, and dispatch scene generation to separate Veo and Omni adapters. Repair the reviewed request, output, media, upload and lifecycle defects in the same feature. Existing entry points are VideoReelHandler, GoogleGeneration.generate_video_reel and GoogleGeneration.video_generation [F001,F002]. Omni requires asynchronous Interactions rather than Veo operation polling; the installed SDK supports it [F005,F006]. Recommendation: retain Veo as the default, allow per-scene overrides, and avoid automatic cross-model retries.

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

### 2.2 Constraints

- Async provider I/O, Pydantic v2 and satellite ownership remain binding; core request models cannot import provider enums [F007].
- Preserve existing POST 202 and polling behavior, augment JSON schema, keep provider imports lazy [F001].
- Keep AIMessage.files for actual local paths; add typed reel descriptors in existing metadata/artifacts [F003].
- Resolve SDK resource ownership in Google generation code. The shared base client is a verified dependency, not an authorized broad refactor [F004].
- Prior tests do not establish an end-to-end pass: 42 passed, 3 storage-stub failures, 20 fixture errors, 1 skipped [F003].

### 2.3 Recent History

Provider extraction on 2026-09-04 (7f7f6f165, a0471ded2, 77b599141), formatting on 2026-09-05 (14b548483), and handler satellite move on 2026-05-29 (434423d45) explain current locations. No defect causality is inferred solely from history [F007].

## 3. Probable Scope

### New capability

Propose video_model at reel level (default veo-3.1-generate-preview), with nullable scene-level video_model overrides. Supported selection includes Veo standard/Fast/Lite and gemini-omni-1.1-flash. A reel may assemble clips from both API families. This is local clip composition, not uploading a Veo clip to Omni for editing [F002,F005,F008].

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

- Keep the legacy top-level model meaning separate; video_model selects the video backend.
- Scene duration is an edit target. Request a supported Veo duration covering it and trim locally. Omni initially uses provider-default generation length and trims when possible; no invented duration enum. Fail clearly if actual output is too short.
- Preserve separate narration/music as the default audio mode and mute model audio. Add an explicit native-audio mode; reject simultaneous separate narration/music settings until mixing is deliberately supported.
- Default partial_failure_policy=fail; opt-in skip yields per-scene errors and a partial marker.
- No cross-model automatic fallback, safety-block resubmission, multi-turn editing, video extension or UI overhaul in this scope.
- Use owned SDK clients with deadlines. Retrying reads/downloads is distinct from resubmitting a billable generation request after an ambiguous timeout.
- Keep native URI fetching behind an adapter boundary with authenticated Google-origin requests or signed downloads; do not forward credentials to arbitrary redirect hosts.

These are recommendations for review, not answers attributed to the user.

## 4. Confidence Map

| Claim | Evidence | Confidence | Basis |
|---|---|---|---|
| Handler and scene orchestration are localized | F001,F002 | high | Source and wiki |
| Existing output/audio/upload defects are reproduced | F003 | high | Persisted probes |
| SDK 2.23.0 exposes async Omni transport/output fields | F006 | high | Offline introspection and installed source |
| Omni and Veo can normalize to a shared clip assembly contract | F002,F005,F006 | medium | Architecture inference; no live generation |
| Veo 3.1 remains available in the documented catalog | F008 | high | Official documentation |
| Live account/region access and Omni duration behavior | F005,F006 | low | Not exercised |

Overall: medium. Proposal/spec drafting is justified; implementation cannot claim live readiness without smoke verification.

## 5. Open Questions

Resolved through research: Omni requires a separate API adapter [F005,F006]; Veo remains the compatibility default [F008].

Unresolved user decisions (asked asynchronously; no answer received):
1. Confirm reel default plus scene overrides versus one model per reel.
2. Confirm proposed scope excluding automatic fallback and conversational editing.

Implementation evidence gates: verify Omni duration semantics and URI download authentication on the selected SDK; verify deployed identity/tenant access conventions before wiring artifact access. These are research tasks, not questions asking the user to guess API behavior.

## 6. Recommended Next Step

A formal draft spec is produced alongside this proposal at sdd/specs/video-reel-omni-veo-reliability.spec.md. Review the proposed policies before marking it approved and running sdd-task. No implementation tasks are created here.

## 7. Research Audit

- State: sdd/state/FEAT-564/state.json
- Source snapshot: source.md and review-source.md
- Research plan: research_plan.json
- Findings: findings/F001–F008
- Synthesis: synthesis.json
- No paid API generation or new dependency installation.
- Research budget: loose profile; 100 files, 60 searches, 20 git inspections, depth 3, 900 seconds. Prior review reused; synthesis does not claim new test execution.
- Template discrepancy: plan prompt requires wiki priority 0, but plan schema excludes wiki query types. Completed wiki orientation is recorded in extensible plan metadata; schema-valid read queries cover persisted evidence.

## 8. Provenance

sdd-proposal enrichment workflow, followed by sdd-spec draft generation. Official sources checked 2026-09-17; installed SDK 2.23.0. Explicit user approval of draft policies remains pending.
