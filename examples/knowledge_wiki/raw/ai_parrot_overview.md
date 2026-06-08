# AI-Parrot Overview

AI-Parrot is an async-first Python framework for building AI agents and
chatbots. It is vendor-agnostic: OpenAI, Anthropic, Google GenAI, Groq and
others are reachable through a single `AbstractClient` interface, so agent code
never talks to a provider SDK directly.

## Core abstractions

- **AbstractClient** — the unified LLM interface. Every provider implements
  `completion`, `stream` and `embed`.
- **Agent / Chatbot** — `Chatbot` is conversational and single-LLM; `Agent`
  runs a tool-using, ReAct-style reasoning loop.
- **Tools and toolkits** — agents act on the world through tools. Simple
  functions use the `@tool` decorator; richer collections subclass
  `AbstractToolkit`. Every tool's docstring becomes its LLM-facing description.
- **AgentCrew** — orchestrates multiple agents sequentially, in parallel, or as
  a dependency DAG.

## Knowledge subsystems

AI-Parrot ships three complementary knowledge subsystems that together form a
durable, agent-maintained knowledge repository:

- **PageIndex** — hierarchical "wiki pages": a JSON table-of-contents plus
  per-node markdown sidecars, with hybrid BM25 + LLM-walk search.
- **GraphIndex** — a knowledge graph (an in-memory graph plus a FAISS index)
  that an agent can both query and *grow* through write tools.
- **Ontology** — a structured entity layer for tenant-scoped, authority-aware
  retrieval, backed by a graph database.

The design goal is a knowledge base the agent contributes back to, rather than
re-deriving every answer from raw text on each query.
