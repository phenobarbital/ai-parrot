"""Built-in guardrail plugins (FEAT-396).

Each module here defines one concrete `Guardrail` subclass, registered by
name in `parrot.bots.guardrails.registry`. Importing this package does NOT
import any individual plugin module — the registry resolves each plugin
lazily, only when it is actually requested by name (see
`registry._make_lazy_factory`), so e.g. importing `parrot.bots.guardrails`
never pulls in `pytector`/`torch` unless `PromptInjectionGuardrail` is
actually registered for a bot.
"""
