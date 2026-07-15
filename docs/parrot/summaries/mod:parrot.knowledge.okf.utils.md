---
type: Wiki Summary
title: parrot.knowledge.okf.utils
id: mod:parrot.knowledge.okf.utils
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared filesystem utilities for the OKF package.
relates_to:
- concept: func:parrot.knowledge.okf.utils.flatten_concept_id_for_filename
  rel: defines
---

# `parrot.knowledge.okf.utils`

Shared filesystem utilities for the OKF package.

Functions here are domain-agnostic helpers used by both PageIndex and
GraphIndex projection layers.  They live in ``okf`` (the neutral shared
package) rather than in either index's sub-package to avoid cross-domain
import dependencies.

## Functions

- `def flatten_concept_id_for_filename(concept_id: str) -> str` — Convert a slash-containing concept_id to a flat filename stem.
