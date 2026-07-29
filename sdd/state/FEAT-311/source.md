---
kind: inline
jira_key: null
fetched_at: 2026-07-16T12:00:00Z
summary_oneline: "Create MoonshotClient for Kimi Moonshot LLM (OpenAI-compatible API)"
---

# Moonshot Client (MoonshotClient)

## Proposal:

Create a new LLM Client from Kimi Moonshot.
Based on openai-compatible, create a MoonshotClient for using the kimi.ai models:

api key env variable for by-default connection:
MOONSHOT_API_KEY

## Model List:
- kimi-k3
- kimi-k2.7-code
- kimi-k2.7-code-highspeed
- kimi-k2.6
- moonshot-v1-128k
- moonshot-v1-8k-vision-preview (for visual understanding)
- moonshot-v1-128k-vision-preview

Compatibility with OpenAI API: https://platform.kimi.ai/docs/guide/migrating-from-openai-to-kimi

## Features to be covered:
- Thinking Mode: https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model
- Multiturn control: https://platform.kimi.ai/docs/guide/engage-in-multi-turn-conversations-using-kimi-api
- Streaming: https://platform.kimi.ai/docs/guide/utilize-the-streaming-output-feature-of-kimi-api
- structured output (JSON mode): https://platform.kimi.ai/docs/guide/use-json-mode-feature-of-kimi-api
- vision model: https://platform.kimi.ai/docs/guide/use-kimi-vision-model
- Context Caching: https://platform.kimi.ai/docs/guide/use-context-caching-feature-of-kimi-api
- Tool Calling: https://platform.kimi.ai/docs/guide/use-kimi-api-to-complete-tool-calls

## Using kimi-k2.7-code for Code Agents (dev-loop)
