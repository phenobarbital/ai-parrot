---
type: Wiki Summary
title: parrot.tools.working_memory.conftest
id: mod:parrot.tools.working_memory.conftest
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Conftest for working_memory package tests.
---

# `parrot.tools.working_memory.conftest`

Conftest for working_memory package tests.

Patches parrot.tools.__getattr__ to raise AttributeError instead of ImportError
for unknown names. This is necessary because parrot.tools.__getattr__ raises
ImportError (not AttributeError) for unrecognised tool names, which breaks pytest's
getattr(mod, name, default) calls for names like 'pytest_plugins', 'setUpModule',
'tearDownModule', etc. — causing the default value to be bypassed and ImportError
to propagate.
