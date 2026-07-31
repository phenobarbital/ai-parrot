---
type: Wiki Summary
title: parrot.observability.recorders.factory
id: mod:parrot.observability.recorders.factory
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: build_recorders_from_config — map an ObservabilityConfig to recorder backends.
relates_to:
- concept: func:parrot.observability.recorders.factory.build_recorders_from_config
  rel: defines
- concept: mod:parrot.observability.config
  rel: references
- concept: mod:parrot.observability.recorders.base
  rel: references
- concept: mod:parrot.observability.recorders.logging_recorder
  rel: references
- concept: mod:parrot.observability.recorders.prometheus_recorder
  rel: references
---

# `parrot.observability.recorders.factory`

build_recorders_from_config — map an ObservabilityConfig to recorder backends.

Used by the auto-boot (``ensure_observability_bootstrapped``) to instantiate the
pluggable recorders for the selected ``usage_backend`` without the caller knowing
about concrete backend classes.

## Functions

- `def build_recorders_from_config(config: 'ObservabilityConfig') -> 'list[AbstractLogger]'` — Return the recorder backends for ``config.usage_backend``.
