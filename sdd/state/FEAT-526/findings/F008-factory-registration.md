# F008 — Factory registration point and alias convention

**Path**: `packages/ai-parrot/src/parrot/clients/factory.py`

- `SUPPORTED_CLIENTS: dict[str, type | callable]` — direct class for cheap
  imports, `_lazy_*()` loader for heavy/optional SDKs.
- Aliases are routine: `"grok"/"xai"`, `"zai"/"z.ai"`, `"moonshot"/"kimi"`,
  `"local"/"localllm"/"ollama"/"llamacpp"`, `"bedrock-mantle"/"mantle"`.
- `LLMFactory.parse_llm_string()` splits `"provider:model"` on the first `:`.
- Unknown provider → `ValueError` listing supported keys.

**Implication**: register `"meta"` plus plausible aliases (`"muse"`,
`"meta-muse"`). Direct import is fine — the client needs only the `openai` SDK,
already a dependency of the other wire clients. `"meta:muse-spark-1.3"` becomes
a valid llm string everywhere `LLMFactory.create()` is accepted.
