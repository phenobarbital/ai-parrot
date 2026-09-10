---
id: F004
query_id: Q006
type: read
intent: Task template: which sections already carry code / guidance for the executor
executed_at: 2026-09-10T01:00:00Z
duration_ms: 400
parent_id: null
depth: 0
---

# F004 — task.md template: Codebase Contract + "Pattern to Follow" + Test Specification, no explained skeleton

## Summary

`sdd/templates/task.md` (175 lines) gives the executor a Codebase Contract (43-70), an Implementation Notes block whose "Pattern to Follow" is a code fence pointing at *existing* code to copy (77-84), a Test Specification scaffold (108-143) and Agent Instructions (147-163). Nothing in the template asks the author to hand the executor a starting-point skeleton of the *new* code with an explanation of each part — the executor is expected to derive it from Scope + Contract.

## Citations

- path: `sdd/templates/task.md`
  lines: 43-48
  symbol: Codebase Contract (Anti-Hallucination)
  excerpt: |
    > The implementing agent MUST use these exact imports, class names, and method signatures.
    > **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

- path: `sdd/templates/task.md`
  lines: 73-94
  symbol: Implementation Notes / Pattern to Follow
  excerpt: |
    ### Pattern to Follow
    ```python
    # Reference implementation pattern from existing code
    # e.g. copy this structure from parrot/loaders/base.py
    class ExistingPattern(AbstractBase):
    ```
    ### Key Constraints
    ### References in Codebase

- path: `sdd/templates/task.md`
  lines: 108-143
  symbol: Test Specification
  excerpt: |
    > Minimal test scaffold. The agent must make these pass.
    ```python
    class Test<Component>:
        def test_initialization(self, component): ...
    ```

- path: `sdd/templates/task.md`
  lines: 147-163
  symbol: Agent Instructions
  excerpt: |
    3. **Verify the Codebase Contract** — before writing ANY code
    5. **Implement** following the scope, codebase contract, and notes above
