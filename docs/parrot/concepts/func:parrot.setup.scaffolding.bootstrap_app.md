---
type: Concept
title: bootstrap_app()
id: func:parrot.setup.scaffolding.bootstrap_app
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generate ``app.py`` and ``run.py`` in the project root.
---

# bootstrap_app

```python
def bootstrap_app(agent_config: object, cwd: Path, force: bool=False) -> bool
```

Generate ``app.py`` and ``run.py`` in the project root.

Skips generation (and emits a warning) if either file already exists
and ``force`` is ``False``.

Args:
    agent_config: ``AgentConfig`` instance used to populate template
        variables for ``app.py``.
    cwd: Project root directory where ``app.py`` and ``run.py`` are
        written.
    force: When ``True``, overwrite existing files without prompting.

Returns:
    ``True`` if both files were written; ``False`` if skipped due to
    pre-existing files.
