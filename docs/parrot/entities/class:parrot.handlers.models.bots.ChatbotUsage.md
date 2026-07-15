---
type: Wiki Entity
title: ChatbotUsage
id: class:parrot.handlers.models.bots.ChatbotUsage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ChatbotUsage.
---

# ChatbotUsage

Defined in [`parrot.handlers.models.bots`](../summaries/mod:parrot.handlers.models.bots.md).

```python
class ChatbotUsage(Model)
```

ChatbotUsage.

Saving information about Chatbot Usage.

-- ScyllaDB CREATE TABLE Syntax --
CREATE TABLE IF NOT EXISTS navigator.chatbots_usage (
    chatbot_id TEXT,
    user_id SMALLINT,
    sid TEXT,
    source_path TEXT,
    platform TEXT,
    origin inet,
    user_agent TEXT,
    question TEXT,
    response TEXT,
    used_at BIGINT,
    at TEXT,
    PRIMARY KEY ((chatbot_id, sid, at), used_at)
) WITH CLUSTERING ORDER BY (used_at DESC)
AND default_time_to_live = 10368000;
