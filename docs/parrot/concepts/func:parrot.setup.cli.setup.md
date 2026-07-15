---
type: Concept
title: setup()
id: func:parrot.setup.cli.setup
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Interactive first-time setup wizard for AI-Parrot.
---

# setup

```python
def setup(force: bool) -> None
```

Interactive first-time setup wizard for AI-Parrot.

Guides you through:


  - Selecting an LLM provider and entering credentials
  - Writing credentials to the correct .env file
  - Optionally creating an Agent in AGENTS_DIR
  - Optionally generating app.py and run.py bootstrap files

Run 'parrot setup --force' to overwrite existing app.py / run.py.
