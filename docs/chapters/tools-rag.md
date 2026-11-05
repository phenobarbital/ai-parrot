# Tools, Loaders & RAG

Agents are only as useful as their tools allow them to act on the world.
Without tools, an agent can only reason in isolation—it cannot access
external data, execute actions, or manipulate the environment. AI-Parrot
treats tools as first-class citizens: a docstring becomes the LLM-facing
description that tells the model what the tool does, and Pydantic models
define the input schema that becomes the function specification sent to
the model. This design philosophy ensures that every tool is self-documenting
and type-safe.

## Key Concepts

- **@tool Decorator**: The fastest path to creating callable tools. Simply
  annotate any async function with `@tool` and it becomes available to any
  agent in your system. The decorator automatically generates the schema
  from the function signature and docstring.
- **AbstractToolkit**: Groups related tools that share state such as
  authentication credentials, client connections, or rate-limit budgets.
  Toolkits provide a clean separation between tool logic and resource
  management, making it easy to compose complex agent behaviors.
- **Loaders**: Transform documents of various formats—PDFs, HTML, DOCX,
  audio transcripts, database rows, web pages—into chunks ready for vector
  storage. Every loader subclasses `BaseLoader` and implements
  `async def load() -> list[Document]`, providing a consistent interface
  for data ingestion.
- **RAG Pipeline**: The complete flow from raw documents to agent context.
  Loaders → chunkers → embeddings → vector store → knowledge retrieval →
  agent context. Each stage is pluggable, allowing you to swap components
  based on your specific requirements.

## What You Can Build

- **Custom toolkits** by grouping related `@tool` functions with shared
  authentication or client state. For example, a GitHub toolkit that
  includes tools for creating issues, reviewing PRs, and managing repos,
  all sharing a single authenticated GitHub client.
- **Document ingestion pipelines** that pull from PDFs, web pages, or
  databases and prepare them for semantic search, enabling your agents
  to answer questions about your internal documents.
- **Multi-origin retrieval** using the MultiStoreSearch toolkit to query
  across vector stores, PageIndex, GraphIndex, and the LLM Wiki simultaneously,
  giving agents access to all your knowledge sources in one search.
- **Agentic workflows** where tools read and write to the LLM Wiki,
  enabling agents to build persistent knowledge that survives restarts
  and can be shared across multiple agents.

## Deep Dive

For implementation details, available toolkits, and configuration options,
see the [Tools & Toolkits](https://github.com/phenobarbital/ai-parrot/wiki/Tools-%26-Toolkits)
and [Stores & Loaders](https://github.com/phenobarbital/ai-parrot/wiki/Stores-%26-Loaders)
sections in the Wiki.