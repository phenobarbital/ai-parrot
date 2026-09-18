# Revision source — user-supplied Google Gemini review

Received 2026-09-17. The following is the supplied review, preserved as input rather than endorsed findings.

```text
  Observed hardcoded model ID for Veo 3.1 suggests potential rigidity and limited support for other Veo models. Parameter extraction in the handler masks potential inconsistencies if model names are not expected. Current audio handlin...
  ### Executive Summary
  Verdict: The code runs with significant caveats and several critical functional mismatches.
  While the fundamental google-genai SDK v2.24.0 API calls (client.aio.models.generate_videos, client.aio.operations.get, client.aio.files.download) remain syntactically compatible, the pipeline between video_reel.py:31 and
  generation.py:1905 suffers from several design bugs, model hardcoding, duration desynchronizations, and an unaddressed live API dependency.
  ──────
  ### Detailed Review Findings

  #### 1. Veo Model Support & google-genai SDK Compatibility

  • Hardcoded Model Identifier:
  In generation.py:2142:
    video_message = await self.video_generation(
        prompt=scene.video_prompt,
        reference_image=final_image_path,
        model=GoogleModel.VEO_3_1,  # "veo-3.1-generate-preview"
        aspect_ratio=aspect_ratio,
        output_directory=output_dir,
        include_audio=False,
    )
  The code hardcodes models.py:65 ("veo-3.1-generate-preview"). Google is transitioning Veo 3.1 to production GA identifiers (veo-3.1-generate-001, veo-3.1-fast-generate-001) alongside Veo 2 (veo-2.0-generate-001).
  • Fragile Model Detection in video_generation:
  In generation.py:921:
    _veo31_models = {GoogleModel.VEO_3_1.value, GoogleModel.VEO_3_1_FAST.value}
    is_veo31 = model_str in _veo31_models
  If any other Veo model is passed (e.g. veo-3.1-generate-001, veo-3.1-lite-generate-preview, or veo-2.0-generate-001), is_veo31 evaluates to False. When is_veo31 is False:
      • resolution (1080p/4K) is dropped with a warning.
      • reference_images is dropped with a warning.
      • last_frame interpolation is dropped with a warning.
      • person_generation constraints are skipped.
  • Native Audio in Veo 3.1:
  In google-genai 2.24.0, types.GenerateVideosConfig now includes generate_audio: bool. However, generation.py:982 does not pass generate_audio in config_kwargs, and generation.py:2145 explicitly passes include_audio=False (post-
  processing by stripping audio via MoviePy), relying instead on TTS + Lyria.
  ──────
  #### 2. The "Model Parameter Illusion" in VideoReelHandler

  • In video_reel.py:199-246:
    model = data.pop("model", "gemini-3.5-flash")
    ...
    client = GoogleGenAIClient(model=model)
    async with client:
        result = await client.generate_video_reel(request=req, ...)
  Passing "model" in the HTTP body creates client.py:101 with that model. However:
      • generation.py:1905 does not accept a model argument.
      • generation.py:2037 hardcodes model = GoogleModel.GEMINI_2_5_FLASH ("gemini-2.5-flash"). It completely ignores client.model.
      • generation.py:2142 hardcodes model = GoogleModel.VEO_3_1.
      • google.py:398 has no fields for video_model, image_model, or model.
      Result: The model field in the HTTP request has zero effect on the actual pipeline.

  ──────
  #### 3. Scene Duration Desynchronization

  • In google.py:387, duration: float = Field(5.0).
  • When calling self.video_generation in generation.py:2139, the duration parameter is omitted.
  • In generation.py:855, duration defaults to 8.
  • Veo 3.1 only supports durations of 4, 6, or 8 seconds (and requires 8 seconds for 1080p/4K or reference images).
  • In MoviePy assembly (generation.py:2382-2394), the raw 8-second clips are appended without trimming to scene.duration.
  • Result: Every scene video is always 8 seconds long (a 4-scene reel is always 32s), regardless of prompt breakdown. If narration is only 3s long, there are 5s of dead silence before the next scene.
  ──────
  #### 4. Background Music Generation via Lyria (models/lyria-realtime-exp)

  • In generation.py:2283, the handler calls generation.py:1162:
    music_client = await self.get_client(http_options={"api_version": "v1alpha"})
    async with music_client.aio.live.music.connect(model="models/lyria-realtime-exp") as session:

  • models/lyria-realtime-exp is a private, gated Google Live experimental endpoint. Standard Gemini API keys return 404/403 or handshake failure.
  • Although lines 2304–2306 catch Exception and return None (allowing video assembly to continue without music), background music will fail for virtually all standard users unless specifically allowlisted by Google.
  ──────
  #### 5. Safety Filter Exception Narrowness

  • In generation.py:2147:
    except RuntimeError as veo_err:
        if "content safety filter" in str(veo_err):
            # Retries as text-to-video without reference image

  • If Google's API rejects the prompt or image immediately during client.aio.models.generate_videos, it raises google.genai.errors.APIError or google.genai.errors.ClientError (not RuntimeError).
  • Because only RuntimeError is caught here, any upstream APIError bypasses the text-to-video retry, falling into the outer except Exception: block, causing that scene to fail completely.
  ──────
  #### 6. Unit Test Regressions in test_video_reel_handler.py

  • Running pytest packages/ai-parrot/tests/test_video_reel_handler.py encounters 20 setup errors:
    AttributeError: property 'request' of 'VideoReelHandler' object has no setter

  • video_reel.py:31 inherits from video_reel.py:14 (aiohttp.web.View), where request is a read-only @property backed by self._request.
  • The unit test fixture in test_video_reel_handler.py:77 attempts h.request = MagicMock(), which fails under Python. It should set h._request = MagicMock() or instantiate VideoReelHandler(mock_request).
  ──────
  ### Suggested Refactor Plan

  To make VideoReelHandler and generate_video_reel robust against recent google-genai updates and modern Veo models:

  1. Schema & Model Flexibility in google.py:398:
      • Add optional fields:
	  • video_model: Optional[str] = "veo-3.1-generate-preview"
	  • director_model: Optional[str] = "gemini-3.5-flash"
	  • resolution: Optional[str] = "720p"

  2. Dynamic Veo Model Detection:
      • In generation.py:921, detect Veo 3.x using pattern matching ("veo-3" in model_str) rather than an exact 2-element set, so GA identifiers like veo-3.1-generate-001 and veo-3.1-fast-generate-001 are fully supported.
  3. Pass Scene Duration & Subclip in Assembly:
      • Clamp scene.duration to 4, 6, or 8 seconds for Veo 3.1, or pass scene.duration to video_generation and subclip clip.subclipped(0, scene.duration) during MoviePy assembly.
  4. Broaden Safety Error Handling:
      • In generation.py:2147, catch both RuntimeError and (errors.APIError, errors.ClientError) for safety policy retries.
  5. Fix Test Fixture:
      • Update packages/ai-parrot/tests/test_video_reel_handler.py:77 to set h._request = MagicMock().
```
