---
type: Wiki Summary
title: parrot.observability.attributes
id: mod:parrot.observability.attributes
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: GenAI SemConv attribute builders and provider mapping.
relates_to:
- concept: func:parrot.observability.attributes.build_after_client_attrs
  rel: defines
- concept: func:parrot.observability.attributes.build_after_invoke_attrs
  rel: defines
- concept: func:parrot.observability.attributes.build_after_tool_attrs
  rel: defines
- concept: func:parrot.observability.attributes.build_before_client_attrs
  rel: defines
- concept: func:parrot.observability.attributes.build_before_invoke_attrs
  rel: defines
- concept: func:parrot.observability.attributes.build_before_tool_attrs
  rel: defines
- concept: func:parrot.observability.attributes.build_client_failed_attrs
  rel: defines
- concept: func:parrot.observability.attributes.build_invoke_failed_attrs
  rel: defines
- concept: func:parrot.observability.attributes.build_message_event_attrs
  rel: defines
- concept: func:parrot.observability.attributes.build_tool_failed_attrs
  rel: defines
- concept: func:parrot.observability.attributes.resolve_gen_ai_system
  rel: defines
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
---

# `parrot.observability.attributes`

GenAI SemConv attribute builders and provider mapping.

FEAT-177 TASK-1229 — pure functions that map FEAT-176 lifecycle events to
OTel attribute dicts. This is the single point of update when OTel SemConv
renames an attribute or a new provider is added.

Spec §2 (Event → Span mapping) and §2 (Provider → gen_ai.system mapping).

## Functions

- `def resolve_gen_ai_system(client_name: str) -> str` — Resolve a ``client_name`` emitted on ``BeforeClientCallEvent`` to the
- `def build_before_invoke_attrs(event: BeforeInvokeEvent) -> dict[str, Any]` — Build OTel attributes for ``BeforeInvokeEvent`` (agent root span start).
- `def build_after_invoke_attrs(event: AfterInvokeEvent) -> dict[str, Any]` — Build OTel attributes for ``AfterInvokeEvent`` (agent root span end).
- `def build_before_client_attrs(event: BeforeClientCallEvent) -> dict[str, Any]` — Build OTel attributes for ``BeforeClientCallEvent`` (client child span start).
- `def build_after_client_attrs(event: AfterClientCallEvent, *, cost_usd: Optional[float]=None) -> dict[str, Any]` — Build OTel attributes for ``AfterClientCallEvent`` (client child span end).
- `def build_client_failed_attrs(event: ClientCallFailedEvent) -> dict[str, Any]` — Build OTel attributes for ``ClientCallFailedEvent`` (client error span end).
- `def build_before_tool_attrs(event: BeforeToolCallEvent) -> dict[str, Any]` — Build OTel attributes for ``BeforeToolCallEvent`` (tool child span start).
- `def build_after_tool_attrs(event: AfterToolCallEvent) -> dict[str, Any]` — Build OTel attributes for ``AfterToolCallEvent`` (tool child span end).
- `def build_tool_failed_attrs(event: ToolCallFailedEvent) -> dict[str, Any]` — Build OTel attributes for ``ToolCallFailedEvent`` (tool error span end).
- `def build_invoke_failed_attrs(event: InvokeFailedEvent) -> dict[str, Any]` — Build OTel attributes for ``InvokeFailedEvent`` (agent root span error end).
- `def build_message_event_attrs(event: MessageAddedEvent) -> dict[str, Any]` — Build OTel span-event attributes for ``MessageAddedEvent``.
