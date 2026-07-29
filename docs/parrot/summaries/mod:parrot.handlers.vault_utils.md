---
type: Wiki Summary
title: parrot.handlers.vault_utils
id: mod:parrot.handlers.vault_utils
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Backward-compatible redirect — vault_utils relocated to parrot.security in
  FEAT-203.
relates_to:
- concept: mod:parrot.security.vault_utils
  rel: references
---

# `parrot.handlers.vault_utils`

Backward-compatible redirect — vault_utils relocated to parrot.security in FEAT-203.

This module was moved to :mod:`parrot.security.vault_utils` in FEAT-203.
This stub re-exports everything from the new location so existing imports
(e.g. ``from parrot.handlers.vault_utils import store_vault_credential``)
continue to work unchanged.
