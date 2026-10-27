# TASK-4819: GraphIndex prefix parity and configuration wiring

**Feature**: FEAT-760 - Prefixed ADR Aliases
**Spec**: `sdd/specs/adr-prefixed-aliases.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4818
**Assigned-to**: unassigned

## Context

Implement this bounded part of FEAT-760, preserving bare ADR compatibility while allowing
configured repository prefixes. The approved spec §§2–7 defines behavior; source contracts
below were checked at `4e3ba6289`. No ADR publication, migration, or new dependencies.

## Scope

Implement M3 in both extractor and production caller. Apply the exact spec grammar; prefix only allowed ADRs, never RFCs. Load config per discovery root so multi-root scans do not leak allowlists.

**NOT in scope**: files outside the table, ADR publish/pull, rewriting bare record identity,
or adding multiple wiki citations per comment/docstring. Tests assigned to another task
remain read-only here. Do not alter existing public defaults beyond this task's scope.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py` | MODIFY | Capture prefixes and retain allowed ADR labels |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py` | MODIFY | Resolve each input root config and pass its allowlist |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio  # existing graphindex/cli.py:30
import re  # existing extractors/code.py:12
from typing import Optional  # existing extractors/code.py:14
from parrot.knowledge.graphindex.extractors.code import CodeExtractor  # cli.py:43
from parrot.knowledge.wiki.project import load_project_config  # project.py:1079; import locally in build_code_graph
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py:84`: `CodeExtractor.__init__(self, tag_set: Optional[set[str]]=None, ignore_file: Optional[str]=None) -> None`.
- Nested `_register(raw_kind: str, number: str, link_target: Optional[str]) -> None` at :594; finditer consumers at :631 and :656.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py:96`: async `build_code_graph(paths, output_dir, *, tenant_id="default", detect_comms=True, community_resolution=1.0, ignore_file=None, title=None, allow_cdn_fallback=True)`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1079`: `load_project_config(root: Path) -> WikiProjectConfig`; absent file supplies defaults, invalid file raises WikiConfigError.
- Future dependency: TASK-4818 supplies `config.decisions.effective_prefixes() -> frozenset[str]`.
- Symbol IDs: `sym:packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py#CodeExtractor`, `sym:packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py#build_code_graph`; `sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_project_config`.
- `OdooCodeExtractor` inherits the constructor; keep new argument optional.

### Does NOT Exist

- CodeExtractor has no known_prefixes field yet.
- There is no wiki/config.py; use wiki.project and keep config imports out of the extractor.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py#CodeExtractor",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py#build_code_graph",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_project_config"
  ]
}
```

## Implementation Notes

- Preserve async I/O and existing parser/storage boundaries; no provider calls or new dependencies.
- Use typed signatures and Google-style docstrings, Black with 120 columns, and targeted Ruff checks.
- `parallel: true`. Consumes DecisionConfig.effective_prefixes() from TASK-4818 (wiki/decisions/models.py). Parser grammar is a spec contract, not an implementation dependency.
- Blueprints are planning scaffolds: complete every bounded gap in implementation, leaving no placeholders.
- No Delegation Contract: test assertions and edge-case bodies still require implementation judgment.

## Implementation Blueprint

### Steps (in order)

1. Update regex, constructor and both callback sites — all capture indices change together.
2. Keep normalization local to the extractor — preserve the plain-data seam and avoid wiki-model coupling.
3. Load each discovery root config asynchronously in the caller — preserve defaults and isolate allowlists.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py` (MODIFY)

Anchor: `    def __init__(` — `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py:84`, occurrences: 1 (verified with `grep -F -c`).

```python
# REPLACE _CITATION_RE at :35; preserve the shared-grammar comment.
_CITATION_RE = re.compile(
    r"\b(?:(?!(?:ADR|RFC)\d{1,5}-)([A-Za-z][A-Za-z0-9]*)-)?(ADR|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE
)

# Extend the constructor, preserving existing parser and ignore setup:
def __init__(
    self, tag_set: Optional[set[str]] = None, ignore_file: Optional[str] = None,
    known_prefixes: Optional[frozenset[str]] = None,
) -> None:
    """Configure extraction with a caller-resolved ADR prefix allowlist."""
    self._known_prefixes = known_prefixes or frozenset()
    # Retain existing constructor body below this assignment.

# Replace the nested signature in _extract_citations:
def _register(prefix: Optional[str], raw_kind: str, number: str, link_target: Optional[str]) -> None:
    """Register a citation, qualifying only recognized ADR namespaces."""
    # FILL IN: norm = PREFIX-ADR-n only for allowed uppercase prefix and ADR;
    # otherwise KIND-n. Keep IDs, deduplication, tags and edges based on norm.

# Update BOTH existing callbacks (docstrings and comment walk):
# _register(match.group(1), match.group(2), match.group(3), node.node_id)
# register(match.group(1), match.group(2), match.group(3), target)
# Update the callback docstring to (prefix, kind, number, link_target).
```

**Why**: Capture index shifts affect both scans; RFC numbering and unconfigured node identity must remain stable.
### `packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py` (MODIFY)

Anchor: `    extractor = CodeExtractor(` — `packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py:132`, occurrences: 1 (verified with `grep -F -c`).

```python
# Inside build_code_graph: local import avoids module-initialization cycles.
from parrot.knowledge.wiki.project import load_project_config

# Move extractor construction into the existing `for base in paths` loop,
# after base.resolve() and discovery_root calculation, before file discovery.
config = await asyncio.to_thread(load_project_config, discovery_root)
extractor = CodeExtractor(
    ignore_file=str(ignore_file) if ignore_file else None,
    known_prefixes=config.decisions.effective_prefixes(),
)
# FILL IN: retain all surrounding discovery, source reading and graph assembly.
# Do not union prefixes from different roots or substitute defaults on invalid config.
```

**Why**: The caller owns config; per-root loading prevents a foreign root from granting namespaces to its neighbor.


### FILL IN checklist

- [ ] AC4/14/15: ADR matches share spec spans; allowed ADR prefixes propagate to title, citation_ref and ID; RFC always remains unprefixed.
- [ ] AC11: None or empty allowlist keeps pre-change IDs, titles and citation_ref, including see-ADR-3 and FS-RFC-2119.
- [ ] Both comment and docstring sites pass all three groups; compact ADR/RFC tokens retain every old reference.
- [ ] CLI uses effective_prefixes per input root (directory, or parent of an individual file), preserves no-config behavior and rejects invalid config without silently losing prefixes.
- [ ] Complete all blueprint bodies; no placeholder may remain in implementation files.

## Acceptance Criteria

- [ ] AC4/14/15: ADR matches share spec spans; allowed ADR prefixes propagate to title, citation_ref and ID; RFC always remains unprefixed.
- [ ] AC11: None or empty allowlist keeps pre-change IDs, titles and citation_ref, including see-ADR-3 and FS-RFC-2119.
- [ ] Both comment and docstring sites pass all three groups; compact ADR/RFC tokens retain every old reference.
- [ ] CLI uses effective_prefixes per input root (directory, or parent of an individual file), preserves no-config behavior and rejects invalid config without silently losing prefixes.
- [ ] The targeted validation commands pass; Ruff is clean on modified Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_graphify_parity.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_cli.py -q`

## Test Specification

Use the file-level commands above. Each acceptance item names the required observable
behavior; the regression tasks add the spec §4 cases in their owned files. For production
tasks, run the existing suites now and leave the additional assertion work to those tasks.
Capture test output in `artifacts/logs/task-4819.log`. The index caches the full
spec validation contract once; do not widen this task to directory-wide pytest.

## Agent Instructions

1. Use `$sdd-start TASK-4819` to provision the feature worktree; never implement on `dev`.
2. Read the spec, check dependency completion in `sdd/tasks/index/adr-prefixed-aliases.json`, and reverify anchors/imports.
3. Implement only the declared files, then run validation and review the diff.
4. Commit scoped code and SDD state, preserving other contributors' changes.
5. Finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and
   the exact implementation HEAD, per `docs/sdd/CODEX.md`; do not hand-move this file.

## Completion Note

Pending; populated by the finalization workflow after implementation and validation.
