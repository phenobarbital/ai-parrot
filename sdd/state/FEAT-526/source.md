---
kind: inline
jira_key: null
fetched_at: 2026-09-04
summary_oneline: New parrot LLM client for Meta Model API (Muse Spark), OpenAI-wire compatible
---

# Source (verbatim user brief)

Slug: `meta-llm-client`

> # New Meta Muse LLM Client
>
> using following documentation: https://dev.meta.ai/docs/sdks
>
> compatible with OpenAI-based APIs:
> ```python
> client = OpenAI(api_key=os.environ["MODEL_API_KEY"], base_url="https://api.meta.ai/v1")
> response = client.responses.create(model="muse-spark-1.1", input="...")
> ```
> and using the ENV variable by default META_API_KEY.
> and the following models: https://dev.meta.ai/docs/models/
>
> ## Task
> Create a new parrot client (parrot.clients) for Meta Muse spark, for real
> test usage, let's use `muse-spark-1.3-contributor` for end-to-end usage tests.
>
> Capabilities to cover: Tool calling, Tool Search, Search grounding,
> Structured Output, Prompt Caching, Token Counting, Chat Completion.
