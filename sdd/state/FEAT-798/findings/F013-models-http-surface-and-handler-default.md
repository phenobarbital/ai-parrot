---
id: F013
query_id: Q022
type: read
intent: "Public HTTP /models surface that enumerates GoogleModel — confirm it still publishes 2.5 ids."
executed_at: 2026-11-04T01:42:07Z
duration_ms: 300
parent_id: null
depth: 0
---

# F013 — /models publishes every GoogleModel value verbatim; the same handler hardcodes gemini-2.5-flash for generation requests

## Summary

`packages/ai-parrot-server/src/parrot/handlers/google_generation.py` exposes `GET ?resource=models` → `{"models": [m.value for m in GoogleModel]}` (lines 38-44, lazy import per FEAT-523; comment says TASK-2848 was to swap it for `LLMFactory.list_models()`), so the six canonical 2.5 values are published to HTTP clients today and vanish the moment the members are deleted. `POST` (107-115) builds `GoogleGenAIClient(model=data.get("model", "gemini-2.5-flash"))` for video/image/music/speech actions — a second, literal 2.5 default on a public endpoint. `LLMFactory.list_models` (`clients/factory.py:247-253`) returns `active` from `client_class.models` and `deprecated` from an optional `deprecated_models` attribute, which `GoogleGenAIClient` does not define.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/google_generation.py`
  lines: 38-44
  symbol: `list_models`
  excerpt: |
    def list_models() -> list[str]:
        # FEAT-523 (TASK-2846): lazy import — core must not import a
        # provider module at module scope (AC-3). TASK-2848 replaces this
        # with LLMFactory.list_models().
        from parrot.clients.google.models import GoogleModel
        return [model.value for model in GoogleModel]

- path: `packages/ai-parrot-server/src/parrot/handlers/google_generation.py`
  lines: 85-89, 107-115
  symbol: `get` / `post`
  excerpt: |
    if resource == "models":
        payload: Dict[str, Any] = {"models": self.helper.list_models()}
    ...
    client = GoogleGenAIClient(model=data.get("model", "gemini-2.5-flash"))

- path: `packages/ai-parrot/src/parrot/clients/factory.py`
  lines: 231-253
  symbol: `LLMFactory.list_models`
  excerpt: |
    ``{"active": [...model values...], "deprecated": [...aliases...]}``
    ...
    return {
        "active": [m.value for m in client_class.models],
        "deprecated": list(getattr(client_class, "deprecated_models", None) or {}),
    }

## Notes

- A `deprecated_models` dict on `GoogleGenAIClient` would surface the retired ids under `deprecated` in `LLMFactory.list_models` without code changes to the factory — but the `/models` handler iterates the enum directly and would not see it. FEAT-688 chose pure deletion (no `deprecated_models`) per its U2 decision.
