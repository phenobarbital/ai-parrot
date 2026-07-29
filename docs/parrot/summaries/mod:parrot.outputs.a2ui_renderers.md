---
type: Wiki Summary
title: parrot.outputs.a2ui_renderers
id: mod:parrot.outputs.a2ui_renderers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2UI concrete renderers (satellite package, Module 5).
---

# `parrot.outputs.a2ui_renderers`

A2UI concrete renderers (satellite package, Module 5).

This is a satellite-owned leaf package (regular ``__init__.py``) contributing the
``parrot.outputs.a2ui_renderers`` namespace. Each renderer module self-registers into
the core registry (``parrot.outputs.a2ui.renderers.register_a2ui_renderer``) on import;
the core ``get_a2ui_renderer`` resolves them via ``importlib`` over this namespace.
