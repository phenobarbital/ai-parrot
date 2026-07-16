---
type: Concept
title: flatten_concept_id_for_filename()
id: func:parrot.knowledge.okf.utils.flatten_concept_id_for_filename
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert a slash-containing concept_id to a flat filename stem.
---

# flatten_concept_id_for_filename

```python
def flatten_concept_id_for_filename(concept_id: str) -> str
```

Convert a slash-containing concept_id to a flat filename stem.

Slashes in ``concept_id`` are replaced with ``--`` (double-dash) for
filesystem compatibility.  ``NodeContentStore._NODE_ID_RE`` only allows
``[A-Za-z0-9_-]{1,64}``; slashes are not in that set.

If the resulting string exceeds ``_MAX_FLAT_ID_LENGTH`` characters, a
deterministic SHA-1 hash suffix is appended to preserve uniqueness.

Args:
    concept_id: OKF concept_id (may contain ``/`` path separators).

Returns:
    Flat filename stem safe for both the local filesystem and
    ``NodeContentStore.save()``.

Examples:
    >>> flatten_concept_id_for_filename("aws-ir")
    'aws-ir'
    >>> flatten_concept_id_for_filename("playbooks/aws-incident-response")
    'playbooks--aws-incident-response'
