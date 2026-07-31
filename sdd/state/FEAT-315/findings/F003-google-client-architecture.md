# F003 — GoogleGenAIClient: the multimodal reference architecture

**Query**: Q002/Q004 · **Type**: wiki_page · `file:packages/ai-parrot/src/parrot/clients/google/client.py` (5,372 lines)

- Composition: `class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis)`
  — a core client class plus **capability mixins** in sibling modules.
- Subpackage layout:
  - `google/client.py` — core: `ask()`, `ask_stream()`, `invoke()`, `question()`,
    `resume()`, batch APIs, tool-calling loop, structured output, model-class
    detection helpers (`_is_gemini3_model`, `_requires_thinking`, ...),
    per-loop client cache (`_ensure_client`/`get_client`/`close`).
  - `google/generation.py` — `GoogleGeneration` mixin: `generate_image(s)`,
    `video_generation`, `generate_speech`, `generate_music_*`, `generate_video_reel`.
  - `google/analysis.py` — `GoogleAnalysis` mixin (1,931 lines).
  - `google/__init__.py` — `from .client import GoogleGenAIClient`;
    alias `GoogleClient = GoogleGenAIClient`; `__all__ = ["GoogleGenAIClient", "GoogleClient", "GoogleModel"]`.
- Lazy SDK guard pattern: module imports never fail when the SDK extra is
  missing; names resolve to `None` and `_require_google_sdk()` raises an
  actionable ImportError at instantiation (client.py header; same note in
  generation.py header).
- One client, many modes: model-string dispatch inside methods (e.g. image
  models vs text models), single factory key `"google"`.

## Citations
- packages/ai-parrot/src/parrot/clients/google/client.py (wiki page, score ctx Q002)
- packages/ai-parrot/src/parrot/clients/google/generation.py (wiki page)
- packages/ai-parrot/src/parrot/clients/google/__init__.py:1-6
