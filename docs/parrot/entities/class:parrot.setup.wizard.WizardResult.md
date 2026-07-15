---
type: Wiki Entity
title: WizardResult
id: class:parrot.setup.wizard.WizardResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Full result of a completed setup wizard run.
---

# WizardResult

Defined in [`parrot.setup.wizard`](../summaries/mod:parrot.setup.wizard.md).

```python
class WizardResult
```

Full result of a completed setup wizard run.

Attributes:
    provider_config: Provider and credentials that were collected
        during the wizard session.
    environment: Target environment string (e.g. ``"dev"``,
        ``"prod"``).
    env_file_path: Path to the ``.env`` file that was written.
    agent_config: Agent scaffolding result. ``None`` if the user
        chose not to create an agent.
    app_bootstrapped: ``True`` if ``app.py`` and ``run.py`` were
        generated successfully.
