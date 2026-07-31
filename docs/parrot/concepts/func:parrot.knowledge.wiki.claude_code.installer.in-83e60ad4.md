---
type: Concept
title: install_claude_integration()
id: func:parrot.knowledge.wiki.claude_code.installer.install_claude_integration
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Install the wiki ↔ Claude Code integration into a repository.
---

# install_claude_integration

```python
def install_claude_integration(root: Path, config: Optional[WikiProjectConfig]=None, git_hook: bool=True, gitignore: bool=True) -> list[str]
```

Install the wiki ↔ Claude Code integration into a repository.

Args:
    root: Repository root.
    config: Wiki project config; loaded/created when omitted.
    git_hook: Install the git post-commit auto-upsert hook.
    gitignore: Add ``.parrot/`` to .gitignore.

Returns:
    Human-readable list of actions performed.
