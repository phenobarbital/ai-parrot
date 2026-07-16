---
type: Wiki Summary
title: parrot.tools
id: mod:parrot.tools
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tools infrastructure for building Agents.
relates_to:
- concept: mod:parrot
  rel: references
- concept: mod:parrot.plugins
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot_tools
  rel: references
---

# `parrot.tools`

Tools infrastructure for building Agents.

Resolution chain for tool imports:
1. Core tools (always available — defined directly in this module)
2. parrot_tools (ai-parrot-tools installed package)
3. plugins.tools (user/deploy-time plugin directory)
4. TOOL_REGISTRY (declarative registry from ai-parrot-tools)
5. Legacy dynamic_import_helper (backward-compat submodule resolution)

Submodule redirector:
  ``from parrot.tools.prophetforecast import X`` is transparently redirected
  to ``from parrot_tools.prophetforecast import X`` when no local submodule
  exists.  This is done via a sys.meta_path finder installed at import time.
