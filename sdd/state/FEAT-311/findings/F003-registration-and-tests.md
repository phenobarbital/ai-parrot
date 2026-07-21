---
id: F003
query_type: read
intent: Understand factory registration and test patterns for new clients
files_read:
  - parrot/clients/factory.py
  - tests/clients/test_openai_fallback.py
---

## Factory Registration Pattern

In `factory.py`, `SUPPORTED_CLIENTS` dict maps string keys to client classes:
```python
"moonshot": MoonshotClient,
"kimi": MoonshotClient,
```

Import at top of factory.py:
```python
from .moonshot import MoonshotClient
```

## Test Pattern

Tests use `__new__` to create minimal instances without `__init__` (avoids API key):
```python
def _make_moonshot_client(**attrs):
    client = MoonshotClient.__new__(MoonshotClient)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client
```

Test file location: `tests/clients/test_moonshot_client.py`

Focus areas for tests:
- Default model, fallback model class attributes
- `client_type` and `client_name` strings
- Capacity error detection (inherited from OpenAIClient)
- Factory creation via `LLMFactory.create("moonshot:kimi-k3")`
- Thinking mode propagation (if enabled)
