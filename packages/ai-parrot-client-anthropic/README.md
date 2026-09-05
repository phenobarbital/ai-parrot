# ai-parrot-client-anthropic

Anthropic (Claude) LLM client satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.anthropic.AnthropicClient` (direct Anthropic API,
plus AWS Bedrock / AWS-workspace backends via `backend=`) and
`parrot.clients.anthropic.ClaudeAgentClient` (the Claude Agent SDK/CLI
agent). Registers itself with `LLMFactory` via the `parrot.clients` entry
point group — no import of this package is required for core AI-Parrot to
know it exists once installed.

The `backend="bedrock"` transport lazily imports
`parrot.clients.amazon.models.translate` — install `ai-parrot-client-amazon`
alongside this package to use it.

```bash
uv pip install ai-parrot-client-anthropic
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
