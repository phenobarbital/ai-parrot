---
type: Concept
title: scrub_git_output()
id: func:parrot.flows.dev_loop.nodes.base.scrub_git_output
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redact credentials from raw git CLI output before surfacing it.
---

# scrub_git_output

```python
def scrub_git_output(text: str) -> str
```

Redact credentials from raw git CLI output before surfacing it.

Scrubs the userinfo of any https remote URL and, defensively, the value of
``GITHUB_TOKEN`` if it appears verbatim. Used by the push paths so a
``git push`` failure message never leaks a token.
