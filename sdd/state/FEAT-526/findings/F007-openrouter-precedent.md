# F007 — `OpenRouterClient` is the closest concrete precedent (~190 lines)

**Path**: `packages/ai-parrot/src/parrot/clients/openrouter.py`

Shape to copy:
```python
class OpenRouterClient(OpenAIBaseClient):
    client_type: str = "openrouter"
    client_name: str = "openrouter"
    _default_model: str = OpenRouterModel.DEEPSEEK_R1.value

    def __init__(self, api_key=None, ..., **kwargs):
        resolved_key = api_key or config.get('OPENROUTER_API_KEY')
        super().__init__(api_key=resolved_key,
                         base_url="https://openrouter.ai/api/v1", **kwargs)
        self.api_key = resolved_key          # re-set: AbstractClient may overwrite
```
Plus: `get_client()` override (custom headers), `_chat_completion()` override
(`extra_body` injection), `list_models()` via `aiohttp`.

Model enums live in a sibling module: `parrot/models/openrouter.py`
(peers: `moonshot.py`, `nvidia.py`, `zai.py`, `groq.py`, `localllm.py`, `vllm.py`).

Credentials resolve through `navconfig.config.get(...)`, not bare `os.environ`.

**Implication**: `parrot/models/meta.py` (enum + tier metadata) +
`parrot/clients/meta.py` mirrors an established, repeated file pairing.
`list_models()` maps cleanly onto Meta's `GET /v1/models`.
