# Migration — FEAT-564: Reliable video reels with Gemini Omni and Veo 3.1

**Feature**: FEAT-564
**Status**: implemented (target: next release after dev integration)
**Affects**: any caller of `GoogleGeneration.generate_video_reel` / the
`POST /api/v1/google/generation/video_reel` HTTP endpoint, and anyone
polling or downloading a queued reel job's result.

## What changed

The video-reel generation pipeline (`GoogleGeneration.generate_video_reel`,
`packages/ai-parrot-client-google/src/parrot/clients/google/generation.py`)
was rewritten for reliability: a registry-backed Veo/Omni dispatch layer, a
stable provider-error taxonomy, explicit timeline/duration math, isolated
music generation, managed-process media assembly, configurable job/scene
deadlines with cancellation-safe cleanup, and (at the HTTP layer)
owner-checked job polling and artifact delivery. See
`sdd/specs/video-reel-omni-veo-reliability.spec.md` for the full design.

**Public entry points are unchanged**:
`GoogleGeneration.generate_video_reel(request, output_directory=None,
file_manager=None, user_id=None, session_id=None) -> AIMessage` and
`POST/GET /api/v1/google/generation/video_reel` keep their existing
signatures/routes. No code changes are required for existing callers that
already use `VideoReelRequest` — but read "Behavior changes" below, since
several BEHAVIORS underneath those unchanged signatures are new.

## Legacy `model` alias behavior

`VideoReelRequest.model` (the legacy top-level field) is a deprecated alias
for `director_model`, not for the video model:

- Supplying only `model` sets `director_model` to that value and appends a
  deprecation warning to `ReelResult.warnings`.
- Supplying both `model` and `director_model` with **differing** values is
  rejected with a `400` validation error before any provider call.
- Supplying both with **identical** values is accepted, with the same
  deprecation warning.
- `model` **never** selects the video model — `video_model` (reel-level,
  with a nullable per-scene `VideoReelScene.video_model` override) is the
  only field that does.

## Stage models and mixed Veo/Omni reels

- **Director** (scene breakdown, only invoked when `scenes` is omitted):
  defaults to `gemini-2.5-flash`, overridable via `director_model`.
- **Image** (background/foreground per scene): defaults to
  `gemini-3.1-flash-image-preview`, overridable via `image_model` — passed
  explicitly to every `generate_image` call, never silently substituted on
  an invalid id.
- **Video**: reel-level `video_model` default plus a nullable per-scene
  `VideoReelScene.video_model` override — a single reel can mix Veo and
  Omni scenes freely. No automatic cross-model fallback and no
  conversational Omni editing exist anywhere in this pipeline.
- Every model id is validated against the capability registry
  (`reel/profiles.py::VideoProfileRegistry`) **before any paid call**,
  including for scenes the director itself produced.

## Duration / edit policy

- A scene's `duration` (edit target) selects the smallest **legal covering
  duration** the resolved backend/resolution combination supports
  (`reel/profiles.py::select_generation_duration`) — e.g. a default 5s
  scene submits a 6s Veo generation at 720p (Veo's resolution-conditioned
  minimum), then is trimmed back to 5s during assembly.
- Output more than one video frame short of the requested edit duration
  fails with `insufficient_duration` — **no automatic regeneration**.
- Timeline math (`reel/timeline.py::plan_timeline`) is exact and worked
  through in the spec: four 5s scenes cut back-to-back total 20s; the same
  four scenes with 0.5s crossfades total 18.5s — both within one frame.
  Skipped scenes (under `partial_failure_policy="skip"`) keep their
  original indices; music duration follows the FINAL assembled length, not
  the originally-requested one.

## Audio / music policy

- `audio_mode`: `"separate"` (TTS narration + optional background music,
  each independently controllable), `"native"` (keep each clip's own
  audio, no narration/music calls at all), `"muted"` (no audio track).
  `"native"`/`"muted"` reject `speech`, `music_prompt`/`music_genre`/
  `music_mood`, and `music_policy="required"` at validation time — not
  silently ignored.
- `music_policy`: `"optional"` (default — best-effort; failure/timeout
  never fails the job, surfaces as a structured `ReelResult.music_status`:
  `"succeeded"`/`"unavailable"`/`"timeout"`/`"failed"`/`"skipped"`/`"off"`),
  `"off"` (no Lyria connection is ever opened), `"required"` (a music
  failure fails the whole job).
- The Lyria/music client (`reel/music.py::ReelMusicService`) is fully
  isolated from the director and video-generation clients — a separate,
  independently-owned `genai.Client`, closed on every exit path including
  cancellation.

## Result URLs and job ownership

- **Job ownership is resolved from the caller's authenticated session,
  never from a request-body `user_id`** (§8 Q7, closed by TASK-3333). A
  `job_id` may come from the route or the `?job_id=` query string;
  supplying both with differing values is rejected (`400`). A missing job
  and a job owned by someone else both surface the SAME non-disclosing
  `404` — a caller cannot distinguish "does not exist" from "not yours". A
  legacy/anonymous job with no recorded owner is denied to **everyone**
  (fail-closed).
- The final artifact is resolved only via
  `GET /api/v1/google/generation/video_reel/{job_id}/artifacts/{artifact_id}`,
  matched by `artifact_id` against `ReelResult.final_artifact` — **never**
  a raw local path anywhere in an HTTP response. Local (`"fs"`/`"temp"`)
  artifacts are streamed directly (`aiofiles`, chunked, never blocking the
  event loop); cloud (`"s3"`/`"gcs"`) artifacts redirect to a **freshly
  re-signed** URL resolved from the artifact's stable `storage_key` — both
  at artifact-delivery time AND on every job-status poll (a signed URL
  recorded at job-completion time can expire long before a caller checks
  back). `AIMessage.model_dump(mode="json")` is what's stored as
  `job.result` — round-trips byte-exact through Pydantic → job storage →
  HTTP JSON (AC10).
- **Known limitation**: cloud signed-URL refresh reconstructs the storage
  backend from *server* environment config (`VIDEO_REEL_STORAGE_BUCKET`/
  `_PREFIX`). A job whose storage config was supplied *per-request* by the
  client (not mirrored in server env) cannot have its signed URL correctly
  refreshed later — the `Job` model would need to persist the original
  storage config to close this gap; out of this feature's scope as
  implemented.

## Tested SDK versions

`google-genai` floor raised from `>=2.18.1` to **`>=2.23.0`**
(`packages/ai-parrot-client-google/pyproject.toml`) — the lowest version
this feature's async surfaces were actually verified against, by direct
introspection of the installed SDK (see
`packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py`,
which fails first if a future SDK release removes/renames any of them):

| Surface | Used by | Verified |
|---|---|---|
| `aio.models.generate_videos` | `reel/veo.py` (Veo submit) | ✅ 2.23.0 |
| `aio.operations.get` | `reel/veo.py` (LRO polling) | ✅ 2.23.0 |
| `aio.files.download` | `reel/veo.py` (clip download) | ✅ 2.23.0 |
| `aio.interactions.create` | `reel/omni.py` (Omni) | ✅ 2.23.0 |
| `aio.live.music.connect` | `reel/music.py` (Lyria) | ✅ 2.23.0 |
| `aio.aclose` | every owned-client adapter | ✅ 2.23.0 |

`2.18.1` (the previous floor) was never tested against these surfaces and
is not claimed to work. This workspace's `uv.lock` currently resolves
`2.24.0`; that version is likewise **not** separately claimed — only what
was actually run against (2.23.0) is declared as the floor. Lazy import:
`parrot.handlers.video_reel` and the reel pipeline's own provider-client
construction import `google.genai`/`GoogleGenAIClient` only inside
functions, never at module scope (FEAT-523 TASK-2846 AC-3) — the rest of
the package stays importable even when `google-genai` is not installed.

## Disabled Vertex entries

The capability registry (`reel/profiles.py::VideoProfileRegistry.default()`)
registers Vertex AI Veo 3.1 GA profiles (`veo-3.1-generate-001`,
`veo-3.1-generate-fast-001`) with **`enabled=False`** — resolving either id
under the `vertex` API surface fails validation (`model_disabled`) before
any paid call, regardless of caller intent. This is deliberate: Vertex Veo
3.1 GA capabilities and credentials for this deployment have not been
verified (§8 Q5, still open — see below). Only the Gemini Developer API
surface (`veo-3.1-generate-preview`/`-fast`/`-lite`, `gemini-omni-1.1-flash`)
is enabled by default.

## Outstanding deployment gates

Four of the spec's five implementation evidence gates (§8) remain **open**
— none is claimed resolved by this feature, regardless of test coverage
level:

- **Q3** — Omni URI authentication, actual output duration/MIME on SDK
  2.23.0: the response SHAPE (`Interaction.status`/`.errors`/
  `.output_video` → `VideoContent.data`/`.uri`/`.mime_type`) is verified
  via OFFLINE SDK source inspection only; the actual Omni video URI
  host/authentication contract is **unverified** — no live call has been
  made. `docs/migration/...` (this file) does not change that.
- **Q4** — Which image model id this deployment actually enables
  (`gemini-3.1-flash-image-preview` vs the enum value
  `gemini-3.1-flash-image`) — unresolved; `image_model` is passed through
  explicitly, so an invalid id will surface as a real provider error rather
  than being silently substituted, but which id is *correct* for a given
  deployment is not verified here.
- **Q5** — Verified Vertex Veo 3.1 GA capabilities and credentials — see
  "Disabled Vertex entries" above; both Vertex profiles stay
  `enabled=False` until this gate closes.
- **Q6** — Lyria `api_version` (`v1alpha` vs the public example's
  `v1beta`) and PCM rate/channels/width — `ReelMusicService` defaults to
  `v1beta`; verified against the wire-reported `AudioChunk.mime_type`
  (`"audio/pcm;rate=<hz>"`) field for the RATE specifically, but the
  broader api_version choice itself is not separately re-verified here.

**Q7** (deployed owner/tenant helper for job/artifact authorization,
local artifact-serving convention) is the one gate this feature **does**
close — see "Result URLs and job ownership" above and TASK-3333's
Completion Note (`sdd/tasks/completed/TASK-3333-reel-artifact-delivery.md`)
for the full evidence trail.

**No live-service readiness claim is made anywhere in this document or the
opt-in `live_google` smoke suite** — the smoke suite (see below) exercises
real API calls only when explicitly enabled with real credentials, and even
a successful run of it does not resolve Q3-Q6 on its own; it only confirms
the specific model/scene combination it happened to exercise, on that day,
against that deployment's credentials.

## Opt-in live smoke suite

`packages/ai-parrot-client-google/tests/live/test_reel_smoke.py`, marker
`live_google` (registered in both `pytest.ini` and the root
`pyproject.toml`'s `[tool.pytest.ini_options]`). Skipped by default — the
skip condition is evaluated from environment variables only, at collection
time, and makes no network call. To run for real:

```bash
PARROT_TEST_LIVE_GOOGLE=1 GOOGLE_API_KEY=<real key> \
  pytest -m live_google packages/ai-parrot-client-google/tests/live/test_reel_smoke.py -v
```

Covers: a single Veo scene, a single Omni scene, a mixed Veo+Omni reel,
`audio_mode="native"` (confirms no separate TTS/Lyria calls are made), and
`music_policy="optional"` (confirms a structured, non-fatal `music_status`).
Every test records model / API surface / SDK version / region as a
**redacted** diagnostics JSON file under `artifacts/logs/reel-smoke/` — an
API key or bearer token never lands on disk, by construction
(`reel/errors._redact`).

**Hardened, triple-layered opt-in gate** — added after a near-miss found
while verifying this suite (see this task's Completion Note for the full
account): `GoogleGenAIClient.__init__` resolves `api_key`/
`vertex_project`/`credentials_file` via `navconfig`'s `config.get(...)`,
**not** raw `os.environ` — an environment with ANY of these configured
via navconfig (for unrelated, ambient dev/testing purposes) could let a
smoke test reach a real call even when the test's own `os.environ`-based
check found nothing. Three independent mechanisms now gate this suite, so
a bug in any one does not silently let a real call through:

1. Each test class is `@pytest.mark.skipif`-decorated based on
   `os.environ["PARROT_TEST_LIVE_GOOGLE"] == "1"` AND
   (`GOOGLE_API_KEY` or `GOOGLE_APPLICATION_CREDENTIALS`) being set.
2. `tests/live/conftest.py`'s `pytest_collection_modifyitems` hook
   independently re-checks the SAME condition and force-applies a skip
   marker to every item collected under `tests/live/`, regardless of
   what the test module itself declared — the same proven pattern
   `packages/ai-parrot/tests/conftest.py` already uses for its own
   `real_llm` marker.
3. Every test constructs its client with an EXPLICIT
   `GoogleGenAIClient(api_key=os.environ["GOOGLE_API_KEY"])` — never a
   bare `GoogleGenAIClient()` that could silently fall back to whatever
   `navconfig` resolves. If somehow reached without `GOOGLE_API_KEY` in
   raw `os.environ`, this raises `KeyError` immediately rather than
   attempting a call with an ambient, unintended credential.

## What did NOT change

- `GoogleGeneration.generate_video_reel`'s and
  `VideoReelHandler.post()`/`.get()`'s public signatures.
- The `VideoReelRequest`/`VideoReelScene` Pydantic models' field names
  (only validation behavior around `model`/`director_model`/
  `partial_failure_policy`/audio-mode conflicts is new or tightened).
- The JSON schema catalog served by `GET /api/v1/google/generation/video_reel`
  with no `job_id`.
- `JobStatus`'s enum values (`PENDING`/`RUNNING`/`COMPLETED`/`FAILED`/
  `CANCELLED`) — `CANCELLED` was already a real status; only the HTTP
  handler's status-polling branch for it was missing (now added).
