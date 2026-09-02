---
id: F006
query_id: Q010,Q011,Q016
type: grep
intent: Scope the InquirerPy proposal against the already-declared interactive-prompt library
executed_at: 2026-09-02T21:59:30Z
parent_id: null
depth: 0
---

# F006 — `questionary` is already the repo's interactive-prompt library; `InquirerPy` and `Textual` are absent

## Summary

`questionary>=2.1.1` is a declared **core** dependency and is already the
selection-prompt library at three sites — including `cli/loaders.py`, which
serves `parrot agent`'s own agent picker when no name is passed. `InquirerPy`
would therefore duplicate an established, already-installed dependency covering
the same role. `Textual` appears in **no** `.toml` in the repository — adopting
it is a genuinely new dependency, not an activation of an existing one. `rich`
and `prompt_toolkit` are likewise already core dependencies.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 97-131
  symbol: `[project] dependencies`
  excerpt: |
    "rich>=13.0",
    "click>=8.1.7",
    "prompt_toolkit>=3.0",
    ...
    "questionary>=2.1.1",

- path: `packages/ai-parrot/src/parrot/cli/loaders.py`
  lines: 17,103-120
  symbol: `StandaloneAgentLoader.select_agent`
  excerpt: |
    import questionary
    ...
    """Present an interactive agent picker using questionary.
    Displays a ``questionary.select()`` prompt listing all registered
    ...
    selected = await questionary.select(

- path: `packages/ai-parrot/src/parrot/cli/loaders.py`
  lines: 413
  symbol: `ServerAgentProxy.select_agent`
  excerpt: |
    selected = await questionary.select(

- path: `packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py`
  lines: 1076-1082
  symbol: `InteractiveDecisionNode`
  excerpt: |
    import questionary  # noqa: PLC0415
    ...
    return questionary.select(self.question, choices=self.options).ask()

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 3672-3683
  symbol: per-document apply prompt
  excerpt: |
    import questionary
    ...
    choice = questionary.select(

## Notes

Grep for `textual` across all `*.toml` in the repo returned zero matches —
confirming absence rather than "not found by this query".
Both `questionary` and `InquirerPy` are built on `prompt_toolkit`, so neither
adds a distinct rendering stack; the choice is API preference, not capability.
