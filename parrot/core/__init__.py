"""Shared infrastructure for AI-Parrot.

This package contains cross-cutting infrastructure reused by multiple
subsystems (``parrot.autonomous``, ``parrot.integrations``, etc.):

- ``parrot.core.hooks``  — Hook system (BaseHook, HookManager, HookEvent)
- ``parrot.core.events`` — EventBus (Redis-backed pub/sub)
"""
