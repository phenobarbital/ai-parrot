---
id: F007
intent: Inventory of tests touching GoogleGenAIClient
query_ids: [Q011]
---

# F007 — Existing test coverage

## Citations

`packages/ai-parrot/tests/test_google_client.py` — function list (grep):

```
8:async def test_google_ask():
67:async def test_google_ask_stream():
102:async def test_google_deep_research_ask_accepts_parameters():
141:async def test_google_deep_research_ask_stream_accepts_parameters():
176:def test_google_tool_result_coerces_non_string_keys():
222:def test_safe_extract_text_prefers_parts_over_flattened_response_text():
236:def test_safe_extract_text_skips_thought_parts():
249:def test_truncate_large_list_result():
268:def test_truncate_large_dict_with_list():
290:def test_truncate_result_within_limit():
```

Other test files matching `GoogleGenAIClient` (no detail captured):
- `test_basic_agent_new.py`
- `test_agent_module.py`
- `test_deep_research_mock.py`
- `test_lyria_music_handler.py`
- `test_lyria_batch.py`
- `test_per_loop_cache.py`
- `test_per_loop_cache_integration.py`
- `test_prompt_caching_gemini.py`

## Notes

- There is **no existing test** specifically for the
  `tools + structured_output` two-phase flow. Adding combined-mode coverage
  is greenfield test work.
- The existing `test_google_ask` / `test_google_ask_stream` tests are the
  pattern to follow for the new combined-mode regression tests.
- Two-axis test matrix recommended: `{ask, ask_stream}` × `{two-phase path,
  combined path}`. Each cell should mock the chat layer and verify that
  the correct number of `generate_content` calls is made (1 for combined,
  2 for two-phase).
