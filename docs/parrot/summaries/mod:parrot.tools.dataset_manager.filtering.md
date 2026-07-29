---
type: Wiki Summary
title: parrot.tools.dataset_manager.filtering
id: mod:parrot.tools.dataset_manager.filtering
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DatasetManager common-field filtering sub-package (FEAT-225).
relates_to:
- concept: mod:parrot.tools.dataset_manager.filtering.contracts
  rel: references
---

# `parrot.tools.dataset_manager.filtering`

DatasetManager common-field filtering sub-package (FEAT-225).

Public re-exports so callers can import from the package root:

    from parrot.tools.dataset_manager.filtering import (
        FilterKind,
        FilterOp,
        ValuesSource,
        FilterDefinition,
        FilterCondition,
        FilterResult,
    )
