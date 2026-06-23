---
id: F005
slug: tool-location
query: "Where external API tools live"
type: tree
---

## Finding: External API tools live in packages/ai-parrot-tools/

### Directory structure:
```
packages/ai-parrot-tools/src/parrot_tools/
    bingsearch.py
    massive/
    workday/
    ibkr/
    sassie/
    ...
```

### Also some tools in core:
```
packages/ai-parrot/src/parrot/tools/
    abstract.py
    toolkit.py
    decorators.py
    dataset_manager/
    working_memory/
    openapitoolkit.py
    ...
```

### Pattern:
- Core abstractions (AbstractToolkit, decorators) → `parrot/tools/`
- External API wrappers → `parrot_tools/` (the satellite package)
- Some older tools in `parrot/tools/` directly (nextstop, workday symlinks)

### Correction to SPEC:
- SPEC says `parrot/tools/gigsmart/` — should be `packages/ai-parrot-tools/src/parrot_tools/gigsmart/`
- But user's invocation says `parrot_tools/interfaces/gigsmart/api.py` — need clarification
