---
id: F042
query_id: Q005
type: wiki_page
intent: "Agent definition YAML loading behaviour and BotConfig fields"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FW-005-agent-definition-yaml-shape]
---

# F042 — Existing YAML agent definition = `agent:` + `model:` + `tools:` + `system_prompt` sections; decorator registration derives the same BotConfig by introspection

## Summary

`tests/test_agent_definitions.py` pins the manifest shape: `agent:` (`name`, `class_name`, `module`, `description`, `enabled`, `version`), `model:` (`provider`, `model`, `temperature`, `max_tokens`), `tools:` (`tools: [{name}]`, `toolkits: [..]`), top-level `system_prompt`. `BotConfig.model_dump(mode="json")` is JSON-safe. `@register_agent` builds an equivalent `BotConfig` from class attributes (`model`, `max_tokens`, `system_prompt`, `priority`, `tags`). The fixture `tests/fixtures/agents/marketing.yaml` is the canonical example. There is no `knowledge:`, `rules:`, `tier:`, `capabilities:` or `tools_deny:` section today.

## Citations

- path: `packages/ai-parrot/tests/test_agent_definitions.py`
  lines: 1-60
  symbol: `TestLoadAgentDefinitions.test_bot_config_fields`
  wiki_page_id: file:packages/ai-parrot/tests/test_agent_definitions.py
  score: 1.00
  excerpt: |
    assert config.class_name == "BasicAgent"
    assert config.model.provider == "google"
    assert "JiraToolkit" in config.tools.toolkits
    assert "marketing expert" in config.system_prompt

- path: `packages/ai-parrot/tests/fixtures/agents/marketing.yaml`
  lines: 1-22
  symbol: `agent / model / tools / system_prompt`
  wiki_page_id: file:packages/ai-parrot/tests/fixtures/agents/marketing.yaml
  score: 1.00
  excerpt: |
    agent:
      name: "MarketingAgent"
      class_name: "BasicAgent"
      module: "parrot.bots.agent"
    model: {provider: "google", model: "gemini-2.5-flash", temperature: 0.7}
    tools:
      toolkits: ["JiraToolkit"]
    system_prompt: |
      You are a marketing expert.

## Notes

`expert.yaml` from the source (name/display_name/description/tier/toolkits/tools_deny/knowledge/capabilities/produces) overlaps `agent:`+`tools:` and adds five new blocks. The manifest never names a model (tier → policy), whereas BotConfig accepts `model:` — projection of tier→ModelConfig would happen at load.
