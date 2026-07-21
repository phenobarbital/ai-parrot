---
type: Wiki Summary
title: parrot.integrations
id: mod:parrot.integrations
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Integrations stub — actual implementations are in ai-parrot-integrations.
---

# `parrot.integrations`

Integrations stub — actual implementations are in ai-parrot-integrations.

This stub provides helpful error messages when the satellite package is not
installed.  When ``ai-parrot-integrations`` is installed, Python's implicit
namespace package mechanism (``pkgutil.extend_path`` / PEP 328 implicit
namespaces) merges both distributions' ``parrot/integrations/`` directories
into a single logical package; the satellite's concrete modules are imported
directly and this stub's ``__getattr__`` is bypassed for those names.

Migration notes
---------------
- OAuth2 moved: ``parrot.integrations.oauth2.*`` → ``parrot.auth.oauth2.*``
- Zoom moved:   ``parrot.integrations.zoom.*``   → ``parrot_tools.zoom.*``
