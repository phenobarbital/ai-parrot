---
type: Wiki Summary
title: parrot.handlers.user
id: mod:parrot.handlers.user
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: UserSocketManager - WebSocket Manager with Redis PubSub for User Interactions.
relates_to:
- concept: class:parrot.handlers.user.UserSocketManager
  rel: defines
- concept: mod:parrot.conf
  rel: references
---

# `parrot.handlers.user`

UserSocketManager - WebSocket Manager with Redis PubSub for User Interactions.

This module provides a WebSocket manager that extends navigator's WebSocketManager
with features for:
- JWT-based authentication
- Redis-backed user info storage
- Geolocation tracking
- Channel-based messaging
- Direct user-to-user messaging

## Classes

- **`UserSocketManager(WebSocketManager)`** — WebSocket Manager with Redis PubSub integration for per-user interactions.
