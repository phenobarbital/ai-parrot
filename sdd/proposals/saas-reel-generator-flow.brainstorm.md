---
type: feature
base_branch: dev
---

# Brainstorm: Agentic Reel Generator flow for the SaaS plane

**Date**: 2026-08-09
**Author**: Jesus Lara (investigation by Claude)
**Status**: exploration
**Recommended Option**: Option B
**Depends on**: the `ai-parrot-saas` tenancy layer (tenant context, BYOK
`SecretStore`, `TenantRuntime`) delivered by the Community Manager phase.

---

## Problem Statement

A hospitality tenant should be able to say "make me a Reel for this week's
menu", drop in a few photos, and get back a finished vertical video parked as
a draft — in S3 or by email — with an optional one-click publish to Instagram
or TikTok.

The generation pipeline already exists and is good. What does not exist is any
way for an **agent** to drive it: `generate_video_reel` is reachable only over
HTTP or by constructing a `GoogleGenAIClient` directly. There is no tool
wrapper, so no agent can plan a reel, ask a clarifying question, or retry a
scene. Everything below the agent layer is done; everything at and above it is
missing.

## What already exists (verified against the codebase)

### The HTTP surface

`packages/ai-parrot-server/src/parrot/handlers/video_reel.py` —
`VideoReelHandler(BaseView)`:

- `@classmethod setup(cls, app, route="/api/v1/google/generation/video_reel")`
  registers both the collection route and a `{job_id}` route.
- `POST` returns **202** with `{job_id, status, message, created_at}`; the work
  runs through `JobManager` (`self.request.app['job_manager']`, Redis-backed
  via `configure_job_manager(app, use_redis=True)` in root `app.py`).
- `GET .../{job_id}` returns job status/result; `GET` on the collection returns
  a JSON-Schema catalogue (`video_reel_request`, `video_reel_scene`,
  `aspect_ratios`, `music_genres`, `music_moods`).
- Accepts **JSON or multipart**. `_parse_multipart` handles a flat FormData
  shape, writes uploaded images to `tempfile.mkdtemp(prefix="videoreel_upload_")`,
  strips directory components (path-traversal safe), skips 0-byte Blob
  placeholders while still advancing the index, and sorts parts by
  `f"img_{i:04d}"` to preserve scene order.
- **Two gaps worth naming**: the handler carries *no* auth decorators (unlike
  its neighbours, which use `@is_authenticated()` / `@user_session()`), and its
  class docstring documents `GET ?job_id=<id>` while the code reads
  `match_info` — the docstring is stale.

### The pipeline

`packages/ai-parrot/src/parrot/clients/google/generation.py`, `generate_video_reel`
(around line 2058):

1. `_breakdown_prompt_to_scenes` uses `GEMINI_2_5_FLASH` with a "professional
   video director" system instruction to derive 3–5 scenes when none are given.
2. Music generation runs **concurrently** (`asyncio.create_task`, Lyria via
   `client.aio.live.music.connect`); scenes run **sequentially**, deliberately,
   to preserve order and limit rate-limit pressure.
3. Per scene: background image → optional foreground composite → Veo 3.1
   video → optional narration audio. A notable resilience detail:
   a `RuntimeError` containing `"content safety filter"` triggers a retry as
   pure text-to-video without the reference image; any other `RuntimeError`
   re-raises.
4. `_create_reel_assembly` stitches with MoviePy (lazily imported).
5. Returns an `AIMessage` from `AIMessageFactory.from_video`.

### Models and storage

`packages/ai-parrot/src/parrot/models/google.py` (~L484–595): `VideoReelRequest`
(prompt, scenes, speech, music_prompt/genre/mood, aspect_ratio defaulting to
9:16, transition_type, output_format, reference_images, `storage_backend`
literal `fs|temp|s3|gcs`, storage_config) and `VideoReelScene`.

Server-side storage config **overrides** the client's: `_create_file_manager`
reads `VIDEO_REEL_STORAGE_BACKEND`, `VIDEO_REEL_STORAGE_BUCKET`,
`VIDEO_REEL_STORAGE_PREFIX`, `VIDEO_REEL_OUTPUT_DIR`. A cloud backend requested
without a bucket logs a warning and silently falls back to local. Artifacts are
keyed `{job_prefix}/scenes/scene_{i}_bg.jpeg` etc., with the final URL from
`await file_manager.get_file_url(...)`.

`FileManagerFactory.create("fs"|"temp"|"s3"|"gcs")` in
`packages/ai-parrot/src/parrot/tools/filemanager.py` wraps
`navigator.utils.file` (lazy `S3FileManager` / `GCSFileManager` so importing
does not drag in aioboto3).

### What does NOT exist

- **No agent tool wrapper.** `packages/ai-parrot/src/parrot/tools/` contains
  nothing reel- or video-related.
- **No social publishing of any kind.** A whole-repo content search for
  `instagram`, `tiktok`, `facebook`, `graph.facebook.com` returns zero matches.
  See `saas-social-publishing.brainstorm.md`.
- **No per-tenant storage prefixing** — the env vars are process-global, so two
  tenants would share a bucket prefix.

---

## Constraints & Requirements

- BYOK: the Google key comes from the tenant's `SecretStore`, never from
  process env. That rules out reusing the handler as-is, since
  `GoogleGenAIClient` is constructed inside it from ambient config.
- Generation is minutes-long: the flow must be checkpointable, so **every
  routing predicate must be a CEL string** (the constraint established by the
  Community Manager flow).
- Artifacts must be tenant-scoped in storage and never served cross-tenant.
- Publishing is destructive and public: it needs explicit human approval, not
  agent discretion.

---

## Options Explored

### Option A: Toolkit over the HTTP endpoint

The agent calls the existing `POST /api/v1/google/generation/video_reel` and
polls the job route.

✅ **Pros:** no change to the pipeline; reuses the job plumbing as-is.

❌ **Cons:** the agent would authenticate to its own server; BYOK cannot be
injected (the handler builds its own client from env); the unauthenticated
handler becomes a bigger liability; storage config stays process-global.

📊 **Effort:** Low — and it entrenches the two gaps above.

### Option B: `ReelToolkit` over the client, plus an AgentsFlow — RECOMMENDED

An `AbstractToolkit` wrapping `GoogleGenAIClient.generate_video_reel` directly,
constructed per tenant with a BYOK-configured client, plus a small flow:

```
reel_intake → clarify (HITL gate, optional) → storyboard
            → generate (long-running) → review_gate → deliver
                                                    → publish (optional)
```

✅ **Pros:** BYOK injection is natural (`model_config={"api_key": ...}` — the
verified path); tenant-scoped storage via a per-tenant `FileManager` prefix;
the agent can iterate on the storyboard before spending Veo credits; publishing
sits behind an explicit gate.

❌ **Cons:** more moving parts; needs a durable job/checkpoint story for a
multi-minute generation.

📊 **Effort:** Medium.

📦 **Libraries / Tools:** none new — google-genai, MoviePy and the existing
`JobManager` all already ship.

🔗 **Existing Code to Reuse:**
- `parrot/clients/google/generation.py` — `generate_video_reel`, unchanged
- `parrot/tools/filemanager.py` — `FileManagerFactory`, per-tenant prefix
- `parrot/tools/toolkit.py` — `AbstractToolkit`, with the `_open`/`_close`
  lifecycle hooks for the client session
- `parrot_saas/flows/community_manager/nodes/base.py` — `CMNode` shows the
  mandatory `fsm` field and the CEL-safe result-model pattern
- `handlers/jobs/` — `JobManager` for the 202 + job_id surface

### Option C: Full asset-library product

Adds a media library, versioning, A/B variants and a scheduler.

📊 **Effort:** High. Premature — nothing above is built yet.

---

## Open Questions

- [ ] Does the reel flow reuse the CM flow's `close`/`failure` terminal
      convention, or does long-running generation warrant its own runner?
- [ ] Storage layout per tenant: bucket-per-tenant or prefix-per-tenant? The
      Community Manager phase chose a `tenant_id` column over schema-per-tenant
      for analogous reasons; the same argument likely applies.
- [ ] Is the review gate the lightweight parked-approval used by the CM flow,
      or the full `HumanInteractionManager`? See
      `saas-hitl-escalation.brainstorm.md`.
- [ ] Should `VideoReelHandler` gain auth decorators as part of this work, or
      as an independent fix? It is a real exposure today regardless.

## Recommendation

Option B. The pipeline is the expensive part and it already works; what is
missing is a tenant-aware, agent-drivable façade over it. Build the toolkit
first — it is independently useful and testable — then the flow, and treat
social publishing as a separate feature behind a `SocialPublisher` port.
