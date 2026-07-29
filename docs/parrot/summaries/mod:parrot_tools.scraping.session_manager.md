---
type: Wiki Summary
title: parrot_tools.scraping.session_manager
id: mod:parrot_tools.scraping.session_manager
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SessionManager — BrowserContext lifecycle per session label.
relates_to:
- concept: class:parrot_tools.scraping.session_manager.SessionManager
  rel: defines
- concept: mod:parrot_tools.scraping.flow_models
  rel: references
---

# `parrot_tools.scraping.session_manager`

SessionManager — BrowserContext lifecycle per session label.

Owns a single Playwright ``Browser`` and creates/caches/closes one
``BrowserContext`` per ``session`` label. Sessions sharing a label share
authentication state (cookies, storage); distinct labels are isolated.

Contexts are created lazily on first use and closed deterministically once the
last :class:`FlowNode` referencing a session has completed
(:meth:`close_if_last`), with :meth:`close_all` as a cleanup safety net
(FEAT-222, Module 7).

## Classes

- **`SessionManager`** — Manage Playwright ``BrowserContext``s keyed by session label.
