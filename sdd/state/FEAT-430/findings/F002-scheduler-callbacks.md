# F002 — Scheduler callback substrate and the card gap

**Query:** Q004 (wiki_page + direct read)
**Citations:** `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py`
  :: `BaseSchedulerCallback`, `SendNotifyReportCallback`, `CALLBACK_REGISTRY`,
     `build_scheduler_callback`, `list_supported_callbacks`
**Confidence:** high (direct source read)

## Callback contract (the SPEC-A integration seam)

```python
class BaseSchedulerCallback(NotificationMixin):
    async def run(self, result: Any, *, schedule_id: str,
                  agent_name: str, **kwargs) -> Dict[str, Any]
```

Callbacks already inherit `NotificationMixin` — the Teams path needs no new base class.
The callback consumes the **return value of the scheduled method**. This is precisely
the seam brainstorm §4.1.A step 4 assumes: `refresh_dashboard_artifact()` returns the
context (share_url, title, generated_at) and the delivery callback consumes it.

## Confirmed gap (brainstorm §3.2 is accurate)

`SendNotifyReportCallback.run()` builds a plain message:

```python
message = self.config.get("message") or payload["markdown"] or payload["text"]
response = await self.send_notification(
    message=message, recipients=recipients, provider=provider,
    with_attachments=True, attachments=attachments)
```

No Adaptive Card construction anywhere. The work is a card-aware callback (or a
`card` branch in this one) — narrow, as the brainstorm claims.

## Risk NOT anticipated by the brainstorm

`BaseSchedulerCallback.process_output()` is written for `AIMessage` agent results.
For a non-agent method returning a plain dict it falls through to:

```python
text = getattr(result, "response", None) or getattr(result, "output", None) or str(result)
```

so a dict return from `refresh_dashboard_artifact` **stringifies into the message body**.
Additionally `SendNotifyReportCallback` auto-attaches a CSV when `payload["data"]` is
coercible to a DataFrame (`attach_data` defaults to **True**) — an unwanted attachment
on a card-only send, and a soft violation of HI-4 unless explicitly disabled.

The card-aware callback must define its own payload contract rather than reuse
`process_output()` as-is.
