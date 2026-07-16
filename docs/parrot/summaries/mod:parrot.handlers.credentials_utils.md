---
type: Wiki Summary
title: parrot.handlers.credentials_utils
id: mod:parrot.handlers.credentials_utils
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Backward-compatible redirect — credentials_utils relocated to parrot.security
  in FEAT-203.
relates_to:
- concept: mod:parrot.security.credentials_utils
  rel: references
---

# `parrot.handlers.credentials_utils`

Backward-compatible redirect — credentials_utils relocated to parrot.security in FEAT-203.

This module was moved to :mod:`parrot.security.credentials_utils` in FEAT-203.
This stub re-exports everything from the new location so existing imports
(e.g. ``from parrot.handlers.credentials_utils import encrypt_credential``)
continue to work unchanged.
