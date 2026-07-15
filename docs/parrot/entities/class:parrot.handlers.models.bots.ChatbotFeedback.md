---
type: Wiki Entity
title: ChatbotFeedback
id: class:parrot.handlers.models.bots.ChatbotFeedback
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ChatbotFeedback.
---

# ChatbotFeedback

Defined in [`parrot.handlers.models.bots`](../summaries/mod:parrot.handlers.models.bots.md).

```python
class ChatbotFeedback(Model)
```

ChatbotFeedback.

Saving information about Chatbot Feedback.

-- BigQuery CREATE TABLE Syntax --
CREATE TABLE IF NOT EXISTS `navigator.chatbots_feedback` (
    chatbot_id STRING,
    session_id STRING,
    turn_id STRING,
    user_id INT64,
    at STRING,
    rating INT64,
    like BOOL,
    dislike BOOL,
    feedback_type STRING,
    feedback STRING,
    created_at INT64,
    expiration_timestamp TIMESTAMP
)
OPTIONS(
  expiration_timestamp = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
);
