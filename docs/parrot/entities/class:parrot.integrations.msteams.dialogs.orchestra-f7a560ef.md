---
type: Wiki Entity
title: FormOrchestrator
id: class:parrot.integrations.msteams.dialogs.orchestrator.FormOrchestrator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Orchestrates the form-based interaction flow.
---

# FormOrchestrator

Defined in [`parrot.integrations.msteams.dialogs.orchestrator`](../summaries/mod:parrot.integrations.msteams.dialogs.orchestrator.md).

```python
class FormOrchestrator
```

Orchestrates the form-based interaction flow.

Responsibilities:
1. Register RequestFormTool with the agent
2. Detect when LLM requests a form
3. Coordinate form display and submission
4. Execute target tool after form completion

Flow:
    User message → Agent processes → LLM may call request_form
    → Orchestrator detects form request → Returns FormSchema
    → Wrapper displays form → User fills → Wrapper calls on_complete
    → Orchestrator executes target tool → Returns result

## Methods

- `async def process_message(self, message: str, conversation_id: str, context: Dict[str, Any]=None) -> ProcessResult` — Process a user message with form awareness.
- `async def handle_form_completion(self, form_data: Dict[str, Any], conversation_id: str, turn_context: TurnContext) -> str` — Handle form completion and execute the pending action.
- `async def handle_form_cancellation(self, conversation_id: str)` — Handle form cancellation.
- `def get_pending_execution(self, conversation_id: str) -> Optional[PendingExecution]` — Get pending execution for a conversation.
- `def has_pending_form(self, conversation_id: str) -> bool` — Check if there's a pending form for this conversation.
- `def cleanup_stale_pending(self, max_age_seconds: float=3600)` — Remove stale pending executions.
