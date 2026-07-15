---
type: Wiki Entity
title: WizardRunner
id: class:parrot.setup.wizard.WizardRunner
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrates the full ``parrot setup`` wizard pipeline.
---

# WizardRunner

Defined in [`parrot.setup.wizard`](../summaries/mod:parrot.setup.wizard.md).

```python
class WizardRunner
```

Orchestrates the full ``parrot setup`` wizard pipeline.

Pipeline steps:

1. Import provider package to trigger subclass registration.
2. Present a numbered provider selection menu.
3. Run the chosen provider wizard to collect credentials.
4. Ask for the target environment name (default: ``"dev"``).
5. Check the target ``.env`` for existing keys; offer per-key overwrite.
6. Write credentials to the env file via ``scaffolding.write_env_vars``.
7. Optionally prompt for agent creation and scaffold it.
8. Optionally prompt for app bootstrap (``app.py`` / ``run.py``).
9. Return a ``WizardResult`` summarising everything that was created.

Args:
    force: When ``True``, overwrite existing ``app.py`` / ``run.py``
        without prompting.
    cwd: Project root directory. Defaults to the current working
        directory.

## Methods

- `def run(self) -> WizardResult` — Execute the full setup wizard and return results.
