# Video reel compatibility review — 2026-09-17

## Verdict and scope

The SDK method surface remains compatible, but the complete HTTP pipeline cannot be considered verified or reliable as-is. There are confirmed output, audio, upload and lifecycle defects, plus a Veo request-value mismatch requiring correction and live verification.

Reviewed the handler, request models, Google generation helpers, SDK client lifecycle, job execution, response typing, storage URL behavior and the three existing reel test modules. No production code was changed and no paid generation was requested. Offline probes exercise extracted production methods without the project's test stubs.

## SDK and models

- Installed and locked `google-genai`: 2.23.0; package requirement: >=2.18.1. Version 2.23.0 is also the latest published release checked: https://github.com/googleapis/python-genai/releases/tag/v2.23.0
- Installed MoviePy: 2.2.1.
- `aio.models.generate_videos`, `aio.operations.get(operation)`, `operation.response.generated_videos` and `aio.files.download(file=video)` remain available. Download without a destination still returns bytes. The image payload uses supported `types.Image(image_bytes=..., mime_type=...)` fields.
- The reel hardcodes `veo-3.1-generate-preview`, a currently documented model. Fast and Lite identifiers are documented too; Veo 3.0 is marked deprecated. Veo 3.1 supports 4/6/8-second generation and native audio. Muting downloaded video locally is a valid approach. https://ai.google.dev/gemini-api/docs/veo
- Background images use the documented stable `gemini-3.1-flash-image`: https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image
- Scene breakdown uses `gemini-2.5-flash`; narration uses `gemini-2.5-flash-preview-tts`. The checked deprecation table lists no shutdown date for either: https://ai.google.dev/gemini-api/docs/deprecations
- Music uses `lyria-realtime-exp`. The current guide demonstrates `v1beta`, whereas this code explicitly selects `v1alpha`. This is documentation drift, not proof that alpha has stopped working: https://ai.google.dev/gemini-api/docs/realtime-music-generation

Paths below are relative to the repository. `generation.py` means `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py`; `video_reel.py` means `packages/ai-parrot-server/src/parrot/handlers/video_reel.py`.

## Findings

### 1. High: Veo person-generation values do not match the documented contract

`generation.py:965-986` uppercases all values and forces `ALLOW_ADULT` for image-to-video and `ALLOW_ALL` for text-to-video. Google's Veo guide specifies lowercase `allow_adult` / `allow_all`. The installed SDK accepts arbitrary strings and its serializer forwards uppercase unchanged; the probe confirms the exact wire value. This is a request-contract defect and likely API rejection point, not a reproduced live 400. Use documented values and verify against the deployment's region. The forced text-to-video fallback also ignores documented regional restrictions on `allow_all`.

### 2. High: successful generation returns corrupted URLs

`generation.py:2021-2025` obtains a FileManager URL and passes it into `AIMessage.files`. `packages/ai-parrot/src/parrot/models/responses.py:91` declares this as `List[Path]`; `AIMessageFactory.from_video` directly constructs that model. Path coercion changes `https://bucket/...` into `https:/bucket/...` and `file:///tmp/...` into `file:/tmp/...`. This affects cloud URLs and the local manager's file URI. The default local URI also does not provide an HTTP download endpoint for remote callers. Represent remote URLs separately from filesystem paths and expose a retrievable HTTP artifact URL.

### 3. High: music is encoded using speech PCM settings

`generation.py:2292` passes streamed music to `AbstractClient._save_audio_file` (`packages/ai-parrot/src/parrot/clients/base.py:2697`). That helper hardcodes mono / 24 kHz; the music path declares stereo / 48 kHz. The offline probe feeds one second of 48 kHz stereo PCM and gets a four-second mono WAV. Playback is distorted and timing is wrong. The persisted key also ends in `.mp3` although the bytes are WAV. Preserve the stream's actual format and use the matching extension. Google's model page documents stereo 48 kHz, while its current guide's JavaScript sample explicitly configures 44.1 kHz; don't infer audio settings solely from a generic helper: https://ai.google.dev/gemini-api/docs/models/lyria-realtime-exp

### 4. Medium: model selection and scene timing are disconnected from the request

`video_reel.py:199` extracts `model` and passes it to the client constructor, but the actual generation stages choose their own models. In particular, `_process_scene` at `generation.py:2139` always uses standard Veo 3.1. Selecting Fast/Lite through POST therefore has no effect on the video model. No request field selects the Veo resolution.

The same call omits `scene.duration`, so every successful scene uses the eight-second default. Scene duration is described as an estimate but drives music duration, while breakdown asks for 3–5 seconds; assembly does not reconcile that estimate with actual video or narration duration. Decide whether duration is a target or metadata, and validate/normalize against supported Veo durations accordingly.

Related helper drift: `generate_videos` accepts Lite, but `video_generation` at line 921 excludes Lite from its capability check. Lite text-to-video retains the wrong modality default and Lite resolution/seed options are ignored. Capabilities should be defined per model rather than one two-element set.

### 5. Medium: multipart image correspondence is corrupted

`video_reel.py:151-160` drops empty placeholders and later enumerates only surviving images. An empty first slot followed by an image for scene 2 assigns that image to scene 1. Part-name indices are also not parsed; the order is arrival order. Files are saved under the supplied basename, so repeated filenames overwrite earlier images and several scene entries point to the same last upload. Both placeholder compaction and overwriting were reproduced offline. Keep explicit scene indices and generate unique server-side filenames.

### 6. Medium: upload cleanup and malformed-body handling have gaps

`_parse_multipart` creates a directory before parsing but returns only image paths. The caller cannot clean it when parsing fails, when no nonempty image is received, or when Pydantic validation returns 400. Storage/job setup failures before the background closure also bypass cleanup. Successful JSON decoding is not sufficient validation: bodies such as `[]` or `null` reach `data.pop` outside the parsing guard and become server errors. Require a mapping and keep temporary-directory ownership through every exit path. Multipart `storage_config` is not JSON-decoded, unlike `scenes` and `speech`.

### 7. Medium: provider clients are not deterministically closed

`GoogleGenAIClient.get_client` (`client.py:630`) now explicitly constructs a fresh, uncached SDK client. Generation helpers call it directly for images, video, breakdown, speech and music, without closing the returned client. `GoogleGenAIClient.close` closes only base-class cached entries. In addition, the handler only uses `async with client`; `AbstractClient.__aexit__` at `base.py:1167` closes its optional aiohttp session, not the SDK cache. Repeated jobs therefore leave provider resources without deterministic cleanup. Establish ownership for the per-API-version clients and close them on success, failure and cancellation.

### 8. Medium: jobs can wait indefinitely or complete with missing scenes

The Veo polling loop at `generation.py:1074` has no deadline. `JobManager._run_job` awaits the execution function without a timeout. A stuck operation can stay RUNNING indefinitely. There is no application-level recovery policy for transient poll/download errors.

`_process_scene` catches failures and returns `(None, None)`. The reel drops those scenes and reports success if any remain, without structured partial-failure details. Its outer exception branch additionally appends bare `None`, while the next filter indexes every result as a tuple (`generation.py:1996-2002`). The latter is a latent failure branch; normal `_process_scene` errors are already swallowed internally. The independent music task is not cancelled in an outer finally when reel execution is cancelled.

### 9. Medium: assembly options do not match their advertised behavior

`generation.py:2419` always selects AAC audio, including WebM output. WebM requires a compatible audio codec such as Opus/Vorbis; audio-bearing WebM output is not configured correctly. `output_format` is unrestricted text in the request model, so other values proceed until encoding.

The crossfade at lines 2388–2393 applies `CrossFadeIn` then concatenates without overlap. This fades a new scene in without overlapping the preceding scene, rather than crossfading between scenes. Narration is attached without reconciling its duration against the video. MoviePy readers are closed only on the success path; narration readers are not explicitly tracked for cleanup. Shared local output paths also permit timestamp-based video filename collisions across simultaneous jobs (`_async_save_video_file`, line 1127) and fixed `composite_{index}.png` collisions.

### 10. Deployment boundary: caller-supplied filesystem paths

The handler accepts `output_directory`, scene reference-image paths, request reference-image paths and storage configuration. These are passed through to local writes/reads or backend construction without a handler-level allowed root. Authenticated callers can therefore select locations available to the service account, including local image files sent to the image provider. This needs an explicit trusted-caller contract or server-side path/storage policy. The handler also retrieves jobs by ID without comparing the requesting user to job ownership. Global authentication/authorization middleware was not audited; exploitability depends on that boundary.

### 11. Low: documented query-string polling does not work

The handler docstring advertises `?job_id=...`, but `get()` at `video_reel.py:273` reads only `match_info`. The registered `/{job_id}` route works; the query-string form returns the schema catalog. Support the documented form or correct the contract.

## Verification and test limitations

Command: `pytest packages/ai-parrot/tests/test_google_reel.py packages/ai-parrot/tests/test_video_reel_handler.py packages/ai-parrot/tests/test_video_reel_storage.py -q`.

Result: **42 passed, 3 failed, 20 errors, 1 skipped**. Log: `artifacts/logs/video_reel_review_pytest.log`.

- All 20 handler setup errors assign `h.request`, which is a read-only property of the installed BaseView. These tests never reach the handler.
- The three storage failures use conftest's replacement factory, which always returns a stub LocalFileManager. They do not demonstrate a failure of the real factory; its inspected implementation validates keys and delegates to navigator.
- Pipeline tests mock generation, assembly and/or AIMessageFactory, so they cannot validate SDK wire values, real media output or URL preservation. One music mock still targets `generate_music` instead of `generate_music_stream`.
- `artifacts/video_reel_review_probe.py` independently reproduces the SDK wire value, Path URL coercion, WAV metadata mismatch, empty-slot compaction and upload overwrite. Output: `artifacts/logs/video_reel_review_probe.log`.
- The first sandboxed test attempt could not initialize project logging sockets; the completed run used approved execution outside that sandbox. No provider generation was performed.

## Suggested repair order

1. Correct Veo parameter values, result URL typing and music encoding.
2. Restore real handler/storage tests and add coverage for the reproduced defects.
3. Repair SDK resource ownership, upload indexing/cleanup and job deadlines.
4. Make model capabilities and timing explicit; repair WebM and transitions.
5. Run a small paid end-to-end smoke test in the target account/region: one scene first, then narration/music and configured storage. This remains necessary to establish live service availability and permissions.
