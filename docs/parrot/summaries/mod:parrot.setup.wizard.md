---
type: Wiki Summary
title: parrot.setup.wizard
id: mod:parrot.setup.wizard
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wizard data models and base abstractions for parrot setup.
relates_to:
- concept: class:parrot.setup.wizard.AgentConfig
  rel: defines
- concept: class:parrot.setup.wizard.BaseClientWizard
  rel: defines
- concept: class:parrot.setup.wizard.ProviderConfig
  rel: defines
- concept: class:parrot.setup.wizard.WizardResult
  rel: defines
- concept: class:parrot.setup.wizard.WizardRunner
  rel: defines
- concept: mod:parrot.setup.providers
  rel: references
- concept: mod:parrot.setup.scaffolding
  rel: references
---

# `parrot.setup.wizard`

Wizard data models and base abstractions for parrot setup.

This module defines the three core dataclasses used throughout the setup
wizard pipeline, the ``BaseClientWizard`` abstract base class that all
provider wizards inherit from, and the ``WizardRunner`` that orchestrates
the full setup pipeline.

## Classes

- **`ProviderConfig`** — Collected configuration for a single LLM provider.
- **`AgentConfig`** — Collected configuration for agent scaffolding.
- **`WizardResult`** — Full result of a completed setup wizard run.
- **`BaseClientWizard(ABC)`** — Abstract base class for provider-specific credential wizards.
- **`WizardRunner`** — Orchestrates the full ``parrot setup`` wizard pipeline.
