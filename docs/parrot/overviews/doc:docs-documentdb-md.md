---
type: Wiki Overview
title: Async context manager para cleanup automático
id: doc:docs-documentdb-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'async with DocumentDb() as db:'
---

# Async context manager para cleanup automático
async with DocumentDb() as db:
    await db.write("conversations", data)
# Conexión cerrada automáticamente, background tasks esperadas

# Fire-and-forget con callbacks opcionales
db.save_background(
    "chat_messages",
    message_doc,
    on_success=lambda r: logger.info(f"Saved {r.inserted_id}"),
    on_error=lambda e: alert_slack(e)
)

# Inspección de escrituras fallidas
print(f"Fallos pendientes: {db.failed_writes_count}")
for failed in db.failed_writes:
    print(f"  - {failed.collection}: {failed.error}")

# Retry manual de fallos
result = await db.retry_failed_writes()
print(f"Recuperados: {result['successful']}/{result['total']}")
```