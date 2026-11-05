# Memory & Knowledge

AI-Parrot separates two concerns that often get confused in AI systems:
**memory** for conversation state within a session, and **knowledge** for
long-lived facts, documents, and embeddings used by retrieval-augmented
generation. Understanding this distinction helps you build agents that
remember what was said in the current conversation while also maintaining
access to persistent information across sessions.

## Key Concepts

- **Conversation Memory**: Per-session history that tracks what the user
  said and what the agent responded. AI-Parrot provides several backends:
  `InMemoryConversation` for process-local storage ideal for testing,
  and `RedisConversation` for production-grade, multi-process safe storage
  with configurable TTL (time-to-live) for automatic cleanup.
- **Episodic Memory**: Long-term memory that persists across sessions using
  FAISS vector storage. This enables agents to recall past interactions,
  learn from previous decisions, and build on accumulated experience.
- **Answer Memory**: A caching layer that stores question-answer pairs,
  allowing agents to avoid recomputing identical queries and respond
  instantly to repeat questions.
- **Vector Stores**: Semantic retrieval over documents using backends like
  PgVector (recommended default), Faiss, Milvus, Arango, and BigQuery.
  These form the foundation for RAG pipelines that retrieve relevant
  context based on meaning rather than exact matches.
- **Knowledge Assembly**: The `parrot.knowledge` module retrieves, ranks,
  deduplicates, and formats context chunks with citations for LLM
  consumption, ensuring the agent receives the most relevant information.

## What You Can Build

- **Session-aware chatbots** that remember the last N turns using
  `RedisConversation` with configurable TTL, providing continuity within
  a conversation while respecting privacy through automatic expiration.
- **Cross-session agents** that build on `EpisodicMemoryStore` to learn
  from past interactions, enabling increasingly personalized responses
  as the agent accumulates experience with a user.
- **Semantic search over document collections** by combining vector stores
  with the knowledge assembly pipeline, delivering accurate, cited answers
  drawn from your entire knowledge base.
- **Answer caching systems** with `AnswerMemory` that dramatically reduce
  response latency for frequently asked questions while reducing compute
  costs by avoiding redundant LLM calls.

## Deep Dive

For implementation details, configuration options, and API reference,
see the [Memory section](https://github.com/phenobarbital/ai-parrot/wiki/Memory),
[Knowledge section](https://github.com/phenobarbital/ai-parrot/wiki/Knowledge),
and [Stores & Loaders](https://github.com/phenobarbital/ai-parrot/wiki/Stores-%26-Loaders)
in the Wiki.