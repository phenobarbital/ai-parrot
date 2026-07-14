---
type: Wiki Summary
title: parrot.clients.nova_sonic
id: mod:parrot.clients.nova_sonic
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Amazon Nova 2 Sonic experimental bidirectional voice client (FEAT-302).
relates_to:
- concept: class:parrot.clients.nova_sonic.NovaSonicClient
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.clients.bedrock
  rel: references
- concept: mod:parrot.clients.live
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.models.bedrock_models
  rel: references
- concept: mod:parrot.models.responses
  rel: references
---

# `parrot.clients.nova_sonic`

Amazon Nova 2 Sonic experimental bidirectional voice client (FEAT-302).

Implements :class:`NovaSonicClient`, an :class:`~parrot.clients.base.AbstractClient`
subclass providing bidirectional speech-to-speech via Amazon Nova Sonic's
``InvokeModelWithBidirectionalStream`` API — using the **Pre-Alpha**
``aws_sdk_bedrock_runtime`` SDK (Python >= 3.12 only; boto3/aioboto3 do not
support this operation).

Follows the sender/receiver task architecture pioneered by
:class:`~parrot.clients.live.GeminiLiveClient.stream_voice` (HTTP/2
bidirectional stream instead of a WebSocket), yielding the same
:class:`~parrot.clients.live.LiveVoiceResponse` shape so downstream
consumers (``VoiceChatHandler``) work unchanged.

.. warning::
    **EXPERIMENTAL.** ``aws_sdk_bedrock_runtime==0.7.0`` is Pre-Alpha and its
    API may change before GA — this module isolates every raw SDK call
    behind three thin wrappers (:meth:`NovaSonicClient._open_stream`,
    :meth:`NovaSonicClient._send_event`, :meth:`NovaSonicClient._iter_events`,
    mirroring :class:`~parrot.clients.bedrock.BedrockConverseClient`'s
    ``_sdk_create``/``_sdk_stream`` pattern) so only those need updating if
    the SDK's shape changes.

See ``sdd/specs/bedrock-client-llm.spec.md`` (Module 7) for the full design.

## Classes

- **`NovaSonicClient(AbstractClient)`** — Experimental Amazon Nova 2 Sonic bidirectional speech-to-speech client.
