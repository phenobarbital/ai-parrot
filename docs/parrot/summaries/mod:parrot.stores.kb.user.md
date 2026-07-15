---
type: Wiki Summary
title: parrot.stores.kb.user
id: mod:parrot.stores.kb.user
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.stores.kb.user
relates_to:
- concept: class:parrot.stores.kb.user.SessionStateKB
  rel: defines
- concept: class:parrot.stores.kb.user.UserInfo
  rel: defines
- concept: class:parrot.stores.kb.user.UserPreferences
  rel: defines
- concept: class:parrot.stores.kb.user.UserProfileKB
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.stores.kb.abstract
  rel: references
- concept: mod:parrot.stores.kb.cache
  rel: references
- concept: mod:parrot.stores.kb.redis
  rel: references
- concept: mod:parrot.utils.helpers
  rel: references
---

# `parrot.stores.kb.user`

## Classes

- **`UserInfo(AbstractKnowledgeBase)`** — Class to manage user information.
- **`UserProfileKB(AbstractKnowledgeBase)`** — KB that queries database for user information.
- **`SessionStateKB(AbstractKnowledgeBase)`** — KB that retrieves from session state.
- **`UserPreferences(RedisKnowledgeBase)`** — KB for user preferences stored in Redis.
