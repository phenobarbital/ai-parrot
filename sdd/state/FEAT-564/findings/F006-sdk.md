---
id: F006
query_id: Q006
type: read
intent: Installed SDK support
executed_at: 2026-09-17T01:24:16Z
parent_id: null
depth: 0
---

# F006 — Installed SDK support

## Summary

Offline introspection confirms c.aio.interactions.create/get in 2.23.0. VideoResponseFormat has duration: Optional[str], but does not enumerate allowed duration values. Internal SDK files are evidence only, not proposed import paths. Existing deep research uses synchronous interactions; do not copy it into the new adapter. Set a tested SDK floor or feature guard; minimum 2.18.1 was not verified.

## Citations

- packages/ai-parrot-client-google/pyproject.toml:17 — google-genai>=2.18.1.
- uv.lock — google-genai 2.23.0.
- .venv/lib/python3.12/site-packages/google/genai/_gaos/google_genai.py:396-478 — asynchronous interactions create/get.
- .venv/lib/python3.12/site-packages/google/genai/_gaos/types/interactions/videoresponseformat.py — VideoResponseFormat.
- .venv/lib/python3.12/site-packages/google/genai/_gaos/types/interactions/interaction.py:272 — Interaction.output_video.
- .venv/lib/python3.12/site-packages/google/genai/_gaos/types/interactions/videocontent.py — VideoContent.data and uri.
- packages/ai-parrot-client-google/src/parrot/clients/google/client.py:5153-5220 — _deep_research_ask.
