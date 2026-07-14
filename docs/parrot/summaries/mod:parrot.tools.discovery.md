---
type: Wiki Summary
title: parrot.tools.discovery
id: mod:parrot.tools.discovery
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Multi-source tool discovery for ToolManager.
relates_to:
- concept: func:parrot.tools.discovery.discover_all
  rel: defines
- concept: func:parrot.tools.discovery.discover_from_registry
  rel: defines
- concept: func:parrot.tools.discovery.discover_from_walk
  rel: defines
- concept: func:parrot.tools.discovery.resolve_class
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.discovery`

Multi-source tool discovery for ToolManager.

Two strategies:
1. FAST (declarative): Read TOOL_REGISTRY dicts from each source — no imports needed
2. FULL (walk): pkgutil.walk_packages — imports everything, finds all AbstractTool subclasses

Default: FAST for installed packages, FULL for plugins/ only.

## Functions

- `def discover_from_registry(sources: list[str] | None=None) -> Dict[str, str]` — Fast discovery: read TOOL_REGISTRY dicts from package __init__.py.
- `def discover_from_walk(sources: list[str] | None=None, filter_fn: Callable[[type], bool] | None=None) -> Dict[str, Type[Union[AbstractTool, AbstractToolkit]]]` — Full discovery: walk packages and find all AbstractTool/AbstractToolkit subclasses.
- `def discover_all(sources: list[str] | None=None) -> Dict[str, Union[str, Type]]` — Combined discovery: fast registry + walk for plugins.
- `def resolve_class(dotted_path: str) -> Type` — Resolve a dotted path string to an actual class.
