---
type: Wiki Summary
title: parrot.auth.context
id: mod:parrot.auth.context
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Integration-agnostic per-user context.
relates_to:
- concept: class:parrot.auth.context.UserContext
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
---

# `parrot.auth.context`

Integration-agnostic per-user context.

Carried across integrations (Telegram, MS Teams, Slack, HTTP) so bots and
tools can react to a specific end user without coupling to a channel-
specific session model.

Wrappers are responsible for building a ``UserContext`` from their own
session object and passing it to ``AbstractBot.post_login`` and
``AbstractBot.clone_for_user``.

This module also hosts the shared ``_pctx_var`` :class:`contextvars.ContextVar`
used by ``DatasetManager`` and ``DatabaseQueryTool`` to propagate the current
``PermissionContext`` across async call boundaries without coupling those
modules to each other.

## Classes

- **`UserContext`** — Channel-agnostic identity snapshot for a single end user.
