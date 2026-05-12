---
id: F021
query_id: Q021
type: grep
intent: Confirm the LLM client wiring on Agent (the brainstorm sets `llm_client=self.llm` on the summarizer — is that attribute the actual one?).
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F021 — `self.llm` IS a real property on AbstractBot — gets/sets `self._llm` (an AbstractClient)

## Summary

`AbstractBot` defines `llm` as a property at `parrot/bots/abstract.py:922-928`
that proxies to `self._llm` (typed `Optional[AbstractClient]`). The brainstorm's
`WeeklySecuritySummarizer(llm_client=self.llm)` is correct **provided** the
LLM is already initialized when the summarizer is instantiated. In `Agent`,
`self._llm = self.client` is set at agent construction (line 130-131 of
`agent.py`) — `self.client` is a `GoogleGenAIClient` initialized
unconditionally. So `self.llm` will be a `GoogleGenAIClient` by the time
`agent_tools()` runs. The brainstorm's wiring works.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 410-413
  symbol: _llm attribute initialization
  excerpt: |
    self._llm: Optional[AbstractClient] = None

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 922-928
  symbol: llm property
  excerpt: |
    @property
    def llm(self):
        return self._llm

    @llm.setter
    def llm(self, model):
        self._llm = model

- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 127-131
  symbol: Agent client initialization
  excerpt: |
    ## Google GenAI Client (for multi-modal responses and TTS generation):
    self.client = GoogleGenAIClient()
    # Initialize the underlying AbstractBot LLM with the same client
    if not self._llm:
        self._llm = self.client

- path: `packages/ai-parrot/src/parrot/bots/chatbot.py`
  lines: 206
  symbol: ChatBot _llm default
  excerpt: |
    self._llm = getattr(self, '_llm', 'google')

## Notes

- `Agent.client` (set to `GoogleGenAIClient()`) is also a usable attribute.
  The brainstorm could pass either `self.llm` or `self.client` — both end up
  being the same `GoogleGenAIClient` instance in `Agent`.
- One subtle point: in `ChatBot.__init__` (line 206) `_llm` is set to the
  STRING `'google'` until later resolved. For Agent, the resolution to a
  real client happens during `super().__init__(...)` in `bots/abstract.py:1169`
  (`self._llm = self._create_llm_client(...)`). Make sure the summarizer is
  instantiated AFTER `super().__init__` completes — which `agent_tools()` is.
