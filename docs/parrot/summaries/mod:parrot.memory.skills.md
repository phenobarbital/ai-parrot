---
type: Wiki Summary
title: parrot.memory.skills
id: mod:parrot.memory.skills
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AI-Parrot SkillRegistry Module — Deprecated re-export shim.
relates_to:
- concept: mod:parrot.skills
  rel: references
---

# `parrot.memory.skills`

AI-Parrot SkillRegistry Module — Deprecated re-export shim.

This module has been promoted to the top-level ``parrot.skills`` namespace.
Importing from ``parrot.memory.skills`` will issue a ``DeprecationWarning``.

Migrate to:
    from parrot.skills import <name>
