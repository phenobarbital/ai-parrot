---
id: FC-012
query_id: Q021
type: grep
intent: "Tests that assert on the 2.5 members or ids (the catalogue tests FEAT-688 edited) — they must be updated with the enum."
executed_at: 2026-11-04T01:42:07Z
duration_ms: 500
parent_id: null
depth: 0
---

# FC-012 — 47 test files mention a 2.5 id; the catalogue and defaults tests assert the 2.5 values directly

## Summary

47 test files under `packages/*/tests` and `tests/` reference `gemini-2.5` or `GEMINI_2_5`. Hard dependencies (would fail on deletion/renaming): `tests/clients/test_google_models.py:14,25-26` (asserts `GEMINI_2_5_PRO/FLASH` values and `GEMINI_COMPUTER_USE` value), `tests/unit/test_llm_defaults.py:21-22,29,47-51` and `tests/experts/test_expert_llm_defaults.py:21-23,49` (assert the 2.5 builtin defaults), `tests/bots/flows/crew/test_crew_llm_defaults.py:72-87`, `ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py:63-134` (asserts `gemini-2.5-pro` as AGENT default), `ai-parrot-client-google/tests/unit/test_unopened_client_lifecycle.py:48-100` (uses the members by name). Soft uses (string passed to a mocked client): `tests/test_google_client.py` (48, 98, 176, 758, 1045, 1418 …) and the negative cases at 373-374 that assert 2.5 is *not* combined-call whitelisted and `_model_class_key("gemini-2.5-pro") == "default"` (422).

## Citations

- path: `packages/ai-parrot/tests/clients/test_google_models.py`
  lines: 11-26
  symbol: (catalogue assertions)
  excerpt: |
    assert "GEMINI_COMPUTER_USE" in GoogleModel.__members__
    assert GoogleModel.GEMINI_2_5_PRO.value == "gemini-2.5-pro"
    assert GoogleModel.GEMINI_2_5_FLASH.value == "gemini-2.5-flash"

- path: `packages/ai-parrot/tests/unit/test_llm_defaults.py`
  lines: 21-22, 29-29, 47-51
  symbol: (resolver tests)
  excerpt: |
    assert ld.resolve_component_llm("CREW", builtin="google:gemini-2.5-pro") == ld.ComponentLLM(
        provider="google", model="gemini-2.5-pro", source="builtin"
    monkeypatch.setattr(ld.conf, "DEFAULT_LLM", "google:gemini-2.5-pro")
    env["CREW_LLM"] = "gemini-2.5-pro"

- path: `packages/ai-parrot/tests/experts/test_expert_llm_defaults.py`
  lines: 21-23, 49-49
  symbol: (tier policy tests)
  excerpt: |
    ExpertTier.JUDGMENT: {"provider": "google", "model": "gemini-2.5-pro", "temperature": 0.2},
    assert (judgment.provider, judgment.model, judgment.temperature) == ("google", "gemini-2.5-pro", 0.2)

- path: `packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py`
  lines: 63-63, 77-92, 129-134
  symbol: (AGENT default tests)
  excerpt: |
    assert agent.kwargs["model"] == "gemini-2.5-pro"
    _use_model = "gemini-2.5-flash"

- path: `packages/ai-parrot/tests/test_google_client.py`
  lines: 370-376, 408-408, 422-422
  symbol: (negative whitelist cases)
  excerpt: |
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-3-flash-preview",  # NOT in the prefix list — 3-flash without the .5
    @pytest.mark.parametrize("model", ["gemini-2.5-pro", "gemini-flash-latest", "", None])
    assert client._model_class_key("gemini-2.5-pro") == "default"

- path: `packages/ai-parrot/tests/bots/flows/crew/test_crew_llm_defaults.py`
  lines: 72-72, 87-87
  symbol: (crew default tests)
  excerpt: |
    env["CREW_LLM"] = "google:gemini-2.5-flash"
    assert captured == {"model": "gemini-2.5-flash", "component": "CREW"}

## Notes

- The negative cases in `test_google_client.py` can keep using 2.5 strings as "any non-whitelisted model" examples even after the enum member is removed (prefix gates don't consult the enum), but reviewers may prefer 2.0 ids there.
- Two `ai-parrot-integrations` telegram tests set `w.agent.model = "gemini-2.5"` as an opaque string — cosmetic.
