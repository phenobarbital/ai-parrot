"""Shared fixture vault for all Obsidian test suites (FEAT-392 §4)."""
import json
from pathlib import Path

import pytest

DAILY_NOTE = """---
title: Daily 2026-07-30
tags: [daily, journal]
---
Worked on [[projects/ai-parrot|the parrot]] and reviewed
[[machine-learning#Basics]] before lunch. See also [[orphanless-target]].
"""

PROJECT_NOTE = """---
aliases: [parrot, AI Parrot]
tags: project
---
# AI-Parrot

Framework notes with an embed ![[diagram.png]] and a link to
[[machine-learning]]. Inline #project/status tag here.

```dataview
LIST FROM #project
```
"""

CONCEPT_NOTE = """---
title: Machine Learning
---
# Machine Learning

Tagged #concepts/ml and #ml.

> [!note] Callout
> Callouts must be preserved verbatim.

```python
# not-a-tag inside code
x = 1
```

Linked from daily notes; links back to [[daily/2026-07-30]].
"""

ORPHAN_NOTE = """Just a lonely note with no links and no tags.
"""

BROKEN_LINK_NOTE = """This note points at [[nonexistent-target]] boldly.
"""

DUPLICATE_A = """Duplicate basename one. Links [[machine-learning]].
"""

DUPLICATE_B = """Duplicate basename two (deeper).
"""

CANVAS = {
    "nodes": [
        {"id": "abc", "type": "file", "file": "projects/ai-parrot.md"},
        {"id": "def", "type": "text", "text": "Some canvas text"},
    ],
    "edges": [{"fromNode": "abc", "toNode": "def"}],
}


@pytest.fixture
def fixture_vault(tmp_path: Path) -> Path:
    """Create a small representative Obsidian vault under tmp_path."""
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "old.md").write_text("trashed", encoding="utf-8")

    (vault / "daily").mkdir()
    (vault / "daily" / "2026-07-30.md").write_text(DAILY_NOTE, encoding="utf-8")
    (vault / "projects").mkdir()
    (vault / "projects" / "ai-parrot.md").write_text(PROJECT_NOTE, encoding="utf-8")
    (vault / "concepts").mkdir()
    (vault / "concepts" / "machine-learning.md").write_text(
        CONCEPT_NOTE, encoding="utf-8"
    )
    (vault / "orphan.md").write_text(ORPHAN_NOTE, encoding="utf-8")
    (vault / "broken-link-note.md").write_text(BROKEN_LINK_NOTE, encoding="utf-8")

    # Duplicate basenames in two folders — shortest path must win.
    (vault / "notes.md").write_text(DUPLICATE_A, encoding="utf-8")
    (vault / "deep" / "nested").mkdir(parents=True)
    (vault / "deep" / "nested" / "notes.md").write_text(
        DUPLICATE_B, encoding="utf-8"
    )

    (vault / "assets").mkdir()
    (vault / "assets" / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n000")

    (vault / "canvas").mkdir()
    (vault / "canvas" / "overview.canvas").write_text(
        json.dumps(CANVAS), encoding="utf-8"
    )

    # Non-UTF-8 "note" — must be skipped with a warning, never crash.
    (vault / "non-utf8.md").write_bytes(b"\xff\xfe invalid \xff")

    return vault
