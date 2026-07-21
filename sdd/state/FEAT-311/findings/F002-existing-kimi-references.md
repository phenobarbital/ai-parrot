---
id: F002
query_type: grep
intent: Check for existing Moonshot/Kimi references in the codebase
files_read:
  - parrot/models/nvidia.py
  - parrot/models/groq.py
  - parrot/clients/factory.py
---

## Existing Kimi/Moonshot References

Kimi/Moonshot models are already available through two other providers:

### Nvidia NIM (parrot/models/nvidia.py)
- `KIMI_K2_THINKING = "moonshotai/kimi-k2-thinking"`
- `KIMI_K2_INSTRUCT_0905 = "moonshotai/kimi-k2-instruct-0905"`
- `KIMI_K2_5 = "moonshotai/kimi-k2.5"`

NvidiaClient's default model IS kimi-k2-instruct-0905.

### Groq (parrot/models/groq.py)
- `KIMI_K2_INSTRUCT = "moonshotai/kimi-k2-instruct-0905"`

### Factory Registration (factory.py)
No direct "moonshot" or "kimi" entry exists. These are accessed via
`nvidia:moonshotai/kimi-k2-thinking` or `groq:moonshotai/kimi-k2-instruct-0905`.

### Implication
A native MoonshotClient would add direct access to Moonshot's own API
endpoint (api.moonshot.cn / platform.kimi.ai), with all kimi-k3 and newer
models not available through Nvidia/Groq. Also enables Moonshot-specific
features like context caching via their native API.
