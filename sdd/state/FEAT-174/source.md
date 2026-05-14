---
kind: inline
jira_key: null
fetched_at: 2026-05-15T00:00:00Z
summary_oneline: Homologate ask_stream across all LLM clients to yield str chunks + final AIMessage
---

# Source: Homologate LLM Clients ask_stream

## Current State

| Component         | ask_stream Return Type                 | Yields Final AIMessage? |
|-------------------|----------------------------------------|------------------------|
| GoogleGenAIClient | AsyncIterator[Union[str, AIMessage]]   | Yes (line 2907)        |
| ClaudeClient      | AsyncIterator[str]                     | No                     |
| GPTClient         | AsyncIterator[str]                     | No                     |
| GroqClient        | AsyncIterator[str]                     | No                     |
| GrokClient        | AsyncIterator[str]                     | No                     |
| Gemma4Client      | AsyncIterator[str]                     | No                     |
| HFClient          | AsyncIterator[str]                     | No                     |
| ClaudeAgentClient | AsyncIterator[str]                     | No                     |
| BaseBot           | AsyncIterator[Union[str, AIMessage]]   | Yes (fallback)         |

## Goal

GoogleGenAI already does it: the N-1 yields are `str` (text chunks), and the last yield
is an `AIMessage` with full metadata (usage, tool_calls, turn_id, provider,
structured_output, etc.).

For uniform behavior, each client (claude.py, gpt.py, groq.py, grok.py, gemma4.py, hf.py,
claude_agent.py) should — at the end of the stream — construct and yield an AIMessage
with accumulated metadata, mirroring the GoogleGenAI pattern (lines 2891-2907).
