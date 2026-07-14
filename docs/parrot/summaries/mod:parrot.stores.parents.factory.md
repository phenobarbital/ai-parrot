---
type: Wiki Summary
title: parrot.stores.parents.factory
id: mod:parrot.stores.parents.factory
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory for creating AbstractParentSearcher instances from a config dict.
relates_to:
- concept: func:parrot.stores.parents.factory.create_parent_searcher
  rel: defines
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot.stores.parents.abstract
  rel: references
- concept: mod:parrot.stores.parents.in_table
  rel: references
---

# `parrot.stores.parents.factory`

Factory for creating AbstractParentSearcher instances from a config dict.

This module resolves a JSONB ``parent_searcher_config`` dict (as stored in
``navigator.ai_bots``) into a concrete ``AbstractParentSearcher`` instance.
An empty dict means "no parent searcher" and returns ``None``.  Unknown
``type`` values raise ``ConfigError`` immediately (fail-loud, FEAT-133 G5).

The factory receives the bot's already-configured ``store`` as a kwarg because
``InTableParentSearcher.__init__`` requires the store.  This means the factory
MUST be called AFTER ``bot.configure(app)`` — see FEAT-133 spec §2 R1 and the
sequencing note in ``parrot/manager/manager.py``.

Usage::

    from parrot.stores.parents.factory import create_parent_searcher

    searcher = create_parent_searcher(
        {"type": "in_table", "expand_to_parent": True},
        store=bot.store,
    )

## Functions

- `def create_parent_searcher(config: dict, *, store: Optional['AbstractStore']) -> Optional[AbstractParentSearcher]` — Instantiate a parent searcher from a config dict.
