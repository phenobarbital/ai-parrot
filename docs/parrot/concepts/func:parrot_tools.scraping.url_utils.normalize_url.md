---
type: Concept
title: normalize_url()
id: func:parrot_tools.scraping.url_utils.normalize_url
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Normalize a URL for deduplication.
---

# normalize_url

```python
def normalize_url(url: str, base: str='') -> Optional[str]
```

Normalize a URL for deduplication.

Applies the following transformations:
  1. Resolve relative URLs against *base*.
  2. Convert scheme to lowercase.
  3. Remove ``www.`` prefix from the domain.
  4. Strip query string and fragment.
  5. Remove trailing slash (except for root path ``/``).
  6. Reject non-HTTP(S) schemes (``mailto:``, ``javascript:``, etc.).

Args:
    url: The URL to normalize (absolute or relative).
    base: Base URL used to resolve relative references.

Returns:
    The normalized URL string, or ``None`` if the URL should be
    discarded (empty, malformed, or non-HTTP scheme).
