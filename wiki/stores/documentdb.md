# DocumentDB Usage Patterns

```python
# Async context manager for automatic cleanup
async with DocumentDb() as db:
    await db.write("conversations", data)
# Connection closed automatically, background tasks awaited

# Fire-and-forget with optional callbacks
db.save_background(
    "chat_messages",
    message_doc,
    on_success=lambda r: logger.info(f"Saved {r.inserted_id}"),
    on_error=lambda e: alert_slack(e)
)

# Inspecting failed writes
print(f"Fallos pendientes: {db.failed_writes_count}")
for failed in db.failed_writes:
    print(f"  - {failed.collection}: {failed.error}")

# Manual retry of failures
result = await db.retry_failed_writes()
print(f"Recuperados: {result['successful']}/{result['total']}")
```
