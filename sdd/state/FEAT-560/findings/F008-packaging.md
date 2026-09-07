---
id: F008
query_id: Q001
type: read
intent: Comparar contratos y localizar brechas de paridad de voz
executed_at: 2026-09-07T05:33:34.494414+00:00
parent_id: null
depth: 1
---

# F008 — Las rutas actuales son paquetes satélite y el SDK de voz es opcional.

## Summary

NovaClient compone BedrockConverseBase y NovaAudio. ai-parrot-client-amazon declara aioboto3; el manifiesto documenta aws_sdk_bedrock_runtime como instalación manual para voz. No se propone introducir dependencias ni importar Google desde Amazon.

## Citations

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py`
  lines: 30-43
  symbol: `NovaClient`
  excerpt:

```python
from .audio import NOVA_VOICE_CATALOG, NovaAudio
from .generation import NovaGeneration


class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
    """Unified client for all Amazon Nova models on Bedrock.

    Covers every Nova modality through a single client, mirroring
    :class:`~parrot.clients.google.client.GoogleGenAIClient`:
```

- path: `packages/ai-parrot-client-amazon/pyproject.toml`
  lines: 15-23
  symbol: `project.dependencies`
  excerpt:

```python
dependencies = [
    "ai-parrot>=1.0.0",
    "aioboto3>=13.2.0",
    # NOT declared here: `aws_sdk_bedrock_runtime` (Pre-Alpha, ==0.7.0,
    # Python>=3.12) — NovaClient's voice/audio path imports it lazily
    # (nova/audio.py) with a graceful ImportError, matching how core left
    # it undeclared before this extraction; install it manually to use
    # Nova voice streaming.
]
```
