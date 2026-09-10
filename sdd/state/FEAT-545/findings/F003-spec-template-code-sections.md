---
id: F003
query_id: Q005
type: read
intent: Spec template: which sections already carry code
executed_at: 2026-09-10T01:00:00Z
duration_ms: 400
parent_id: null
depth: 0
---

# F003 — spec.md template already has four Python code blocks; none is "reference implementation"

## Summary

`sdd/templates/spec.md` (195 lines) contains code fences for Data Models (56-60), New Public Interfaces (62-68), Test Data / Fixtures (103-108) and the Codebase Contract (134-146). §3 Module Breakdown (72-86) is prose-only (Path / Responsibility / Depends on) and is the section that "directly map[s] to Task Artifacts" (line 75). There is no slot for an explained reference implementation or for an external design-research cross-check.

## Citations

- path: `sdd/templates/spec.md`
  lines: 55-68
  symbol: Data Models / New Public Interfaces
  excerpt: |
    ### Data Models
    ```python
    class FeatureModel(BaseModel):
        field: type
    ```
    ### New Public Interfaces
    ```python
    class NewComponent:
        async def method(self, param: Type) -> ReturnType:
            ...
    ```

- path: `sdd/templates/spec.md`
  lines: 72-86
  symbol: §3 Module Breakdown
  excerpt: |
    > Define the discrete modules that will be implemented.
    > These directly map to Task Artifacts in Phase 2.
    ### Module 1: <Name>
    - **Path**: `parrot/path/to/module.py`
    - **Responsibility**: What this module does
    - **Depends on**: existing module or Module N from this spec

- path: `sdd/templates/spec.md`
  lines: 125-158
  symbol: §6 Codebase Contract
  excerpt: |
    ### Verified Imports
    ### Existing Class Signatures
    ### Integration Points
    ### Does NOT Exist (Anti-Hallucination)

- path: `sdd/templates/spec.md`
  lines: 162-179
  symbol: §7 Implementation Notes & Constraints
  excerpt: |
    ### Patterns to Follow
    ### Known Risks / Gotchas
    ### External Dependencies

- path: `sdd/templates/spec.md`
  lines: 182-187
  symbol: §8 Open Questions
