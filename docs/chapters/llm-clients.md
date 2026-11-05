# LLM Clients

AI-Parrot talks to every LLM provider through a single `AbstractClient` interface, so the same agent code can run on OpenAI, Anthropic, Google GenAI, Groq, VertexAI or HuggingFace without changes. This abstraction layer is the key to building vendor-agnostic applications that can switch providers or add new ones without rewriting your core logic. The client layer handles all the complexity of different API formats, authentication methods, and response structures, presenting a unified interface to the rest of the framework.

## Key Concepts

- **AbstractClient** — an async base class with `completion()`, `stream()` and `embed()` methods that every provider wrapper inherits from. This interface defines the contract that all clients must implement.
- **Streaming and retries** — the client layer handles streaming responses and retry policies with configurable back-off and partial-response handling. This ensures robustness when dealing with network issues or rate limits.
- **Embeddings** — dense and sparse embedding back-ends used by the RAG pipeline, accessible through the same client interface. These embeddings enable semantic search and retrieval over your documents.

## What You Can Build

- Build a single agent that can switch between different LLM providers at runtime without changing your code, making it easy to experiment with different models or handle provider outages.
- Create a custom client wrapper for a new provider that follows the same async interface, extending the framework's support for additional LLM services.
- Implement a caching layer that stores completions per loop to avoid redundant API calls, reducing costs and improving response times.

## Deep Dive

For API reference, class signatures, and implementation details, see the [Clients section in the Wiki](https://github.com/phenobarbital/ai-parrot/wiki/Home).
