---
type: Wiki Entity
title: ExtractionPlanRegistry
id: class:parrot_tools.scraping.extraction_registry.ExtractionPlanRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Disk-backed registry for ExtractionPlans with cache lifecycle management.
relates_to:
- concept: class:parrot_tools.scraping.base_registry.BasePlanRegistry
  rel: extends
---

# ExtractionPlanRegistry

Defined in [`parrot_tools.scraping.extraction_registry`](../summaries/mod:parrot_tools.scraping.extraction_registry.md).

```python
class ExtractionPlanRegistry(BasePlanRegistry[ExtractionPlan])
```

Disk-backed registry for ExtractionPlans with cache lifecycle management.

Extends ``BasePlanRegistry`` with extraction-specific features:

- success/failure tracking persisted to the registry index JSON so failure
  counts survive service restarts
- automatic invalidation after ``FAILURE_THRESHOLD`` consecutive failures
- pre-built plan loading from a developer-curated directory
- lazy initialisation: ``load()`` and ``load_prebuilt()`` are called on
  the first ``lookup_plan()`` call, keeping the sync ``__init__`` clean

Args:
    plans_dir: Directory for plan files and the ``extraction_registry.json``
        index.  Defaults to ``scraping_plans`` in the current working
        directory.
    prebuilt_dir: Directory containing pre-built plan JSON files.
        Defaults to ``DEFAULT_PREBUILT_DIR`` (the ``_prebuilt/``
        sub-directory shipped with this package).

## Methods

- `async def load_with_prebuilt(self) -> None` — Load the registry index and all pre-built plans from disk.
- `async def register_extraction_plan(self, plan: ExtractionPlan) -> None` — Register an ExtractionPlan in the registry.
- `async def load_plan(self, fingerprint: str) -> Optional[ExtractionPlan]` — Load an ExtractionPlan from disk by fingerprint.
- `async def lookup_plan(self, url: str) -> Optional[ExtractionPlan]` — Look up and load an ExtractionPlan for a URL.
- `async def record_success(self, fingerprint: str) -> None` — Record a successful extraction and reset the consecutive failure count.
- `async def record_failure(self, fingerprint: str) -> None` — Record a failed extraction. Invalidates after ``FAILURE_THRESHOLD`` failures.
- `async def load_prebuilt(self, directory: Path) -> int` — Load pre-built ExtractionPlan JSON files from a directory.
