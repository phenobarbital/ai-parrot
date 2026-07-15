---
type: Wiki Entity
title: BaseClientWizard
id: class:parrot.setup.wizard.BaseClientWizard
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for provider-specific credential wizards.
---

# BaseClientWizard

Defined in [`parrot.setup.wizard`](../summaries/mod:parrot.setup.wizard.md).

```python
class BaseClientWizard(ABC)
```

Abstract base class for provider-specific credential wizards.

To add support for a new LLM provider:

1. Subclass ``BaseClientWizard`` in
   ``parrot/setup/providers/<provider>.py``.
2. Set ``display_name``, ``provider_key``, and ``default_model``
   as class-level string attributes.
3. Implement ``collect()`` with provider-specific ``click.prompt``
   calls (use ``hide_input=True`` for API keys).

No changes to the wizard core are required — new subclasses are
discovered automatically via ``__subclasses__()``.

Example::

    class MyProviderWizard(BaseClientWizard):
        display_name = "My Provider"
        provider_key = "myprovider"
        default_model = "my-model-v1"

        def collect(self) -> ProviderConfig:
            model = click.prompt("Model", default=self.default_model)
            key = click.prompt("MY_API_KEY", hide_input=True)
            return ProviderConfig(
                provider=self.provider_key,
                model=model,
                env_vars={"MY_API_KEY": key},
                llm_string=f"{self.provider_key}:{model}",
            )

## Methods

- `def collect(self) -> ProviderConfig` — Run interactive prompts and return collected provider config.
- `def all_wizards(cls) -> List[BaseClientWizard]` — Return instances of all registered provider wizard subclasses.
