---
type: Concept
title: export_okf_bundle()
id: func:parrot.knowledge.wiki.export.export_okf_bundle
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Project a wiki store into an OKF v0.1 markdown bundle.
---

# export_okf_bundle

```python
async def export_okf_bundle(store: BaseWikiStore, output_dir: Path, wiki_name: str='') -> WikiExportReport
```

Project a wiki store into an OKF v0.1 markdown bundle.

Works with any :class:`BaseWikiStore` backend via ``dump_pages`` /
``dump_edges`` (for the file backend this re-projects the live
bundle into ``output_dir``).

Args:
    store: Source store (any backend).
    output_dir: Bundle root (created if missing).
    wiki_name: Name used in the bundle index header.

Returns:
    A :class:`WikiExportReport`.
