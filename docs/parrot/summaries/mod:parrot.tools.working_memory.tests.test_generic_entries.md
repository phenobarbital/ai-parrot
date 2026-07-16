---
type: Wiki Summary
title: parrot.tools.working_memory.tests.test_generic_entries
id: mod:parrot.tools.working_memory.tests.test_generic_entries
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tests for generic (non-DataFrame) entry support in WorkingMemoryToolkit.
relates_to:
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestBackwardCompat
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestCatalogGenericEntries
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestDetectEntryType
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestDropGeneric
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestEntryType
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestGenericEntrySummary
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestGetResult
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestListMixed
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestSearchStored
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_generic_entries.TestStoreResult
  rel: defines
- concept: mod:parrot.tools.working_memory
  rel: references
- concept: mod:parrot.tools.working_memory.internals
  rel: references
- concept: mod:parrot.tools.working_memory.models
  rel: references
---

# `parrot.tools.working_memory.tests.test_generic_entries`

Tests for generic (non-DataFrame) entry support in WorkingMemoryToolkit.

Covers:
- EntryType enum values
- _detect_entry_type() auto-detection
- GenericEntry.compact_summary() for each EntryType
- WorkingMemoryCatalog.put_generic() / get / drop
- WorkingMemoryToolkit.store_result(), get_result(), search_stored()
- list_stored() with mixed DataFrame + generic entries
- drop_stored() on generic entries
- Backward compatibility: existing DataFrame tools unchanged

## Classes

- **`TestEntryType`** — Verify the EntryType enum has all expected values.
- **`TestDetectEntryType`** — Auto-detection heuristic for Python objects.
- **`TestGenericEntrySummary`** — Type-aware compact_summary for each EntryType.
- **`TestCatalogGenericEntries`** — WorkingMemoryCatalog with generic entries.
- **`TestStoreResult`** — store_result() async tool method.
- **`TestGetResult`** — get_result() async tool method.
- **`TestSearchStored`** — search_stored() async tool method.
- **`TestListMixed`** — list_stored() with both DataFrame and generic entries.
- **`TestDropGeneric`** — drop_stored() works for GenericEntry.
- **`TestBackwardCompat`** — Existing DataFrame tools must be unaffected by FEAT-074 changes.
