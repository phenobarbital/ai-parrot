# Brainstorm: <Title>

**Date**: YYYY-MM-DD
**Author**: <name>
**Status**: exploration | accepted | rejected
**Recommended Option**: <Option Letter>

---

## Problem Statement

<!-- What problem are we solving? Who is affected?
     Why is this needed now? Be specific about the pain point or opportunity. -->

## Constraints & Requirements

<!-- Hard constraints that any solution must satisfy.
     e.g. performance targets, compatibility, budget, timeline, security. -->

- Constraint 1
- Constraint 2

---

## Options Explored

### Option A: <Name>

<!-- Describe this approach in detail. Focus on WHAT it does, not HOW to code it. -->

✅ **Pros:**
- Benefit 1
- Benefit 2

❌ **Cons:**
- Drawback 1

📊 **Effort:** Low | Medium | High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `package-name` | What it does | version, maturity, etc. |

🔗 **Existing Code to Reuse:**
- `path/to/module.py` — description of what to reuse

---

### Option B: <Name>

<!-- Describe this approach in detail. -->

✅ **Pros:**
- Benefit 1

❌ **Cons:**
- Drawback 1

📊 **Effort:** Low | Medium | High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `package-name` | What it does | version, maturity, etc. |

🔗 **Existing Code to Reuse:**
- `path/to/module.py` — description of what to reuse

---

### Option C: <Name>

<!-- Describe this approach in detail. -->

✅ **Pros:**
- Benefit 1

❌ **Cons:**
- Drawback 1

📊 **Effort:** Low | Medium | High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `package-name` | What it does | version, maturity, etc. |

🔗 **Existing Code to Reuse:**
- `path/to/module.py` — description of what to reuse

---

## Recommendation

**Option <X>** is recommended because:

<!-- Explain the reasoning. Reference tradeoffs from the options above.
     Be honest about what you're trading off. -->

---

## Feature Description

<!-- Detailed explanation of the feature as it would be built using the recommended option.
     This should be thorough enough to feed directly into a spec.
     Cover: user-facing behavior, internal behavior, edge cases, error handling. -->

### User-Facing Behavior
<!-- What does the end user see or experience? -->

### Internal Behavior
<!-- How does it work at a high level? No implementation code — describe flow and responsibilities. -->

### Edge Cases & Error Handling
<!-- What happens when things go wrong? Boundary conditions? -->

---

## Capabilities

### New Capabilities
<!-- Capabilities being introduced.
     Use kebab-case identifiers (e.g., user-auth, data-export).
     Each accepted capability maps to a spec file at docs/sdd/specs/<name>.spec.md -->
- `<name>`: <brief description>

### Modified Capabilities
<!-- Existing capabilities whose requirements change.
     Use existing spec names from docs/sdd/specs/. Leave empty if none. -->

---

## Impact & Integration

<!-- Which existing components are affected?
     Are there breaking changes? New dependencies? Deployment changes?
     Consider: APIs, data models, configuration, CI/CD. -->

| Affected Component | Impact Type | Notes |
|---|---|---|
| `component` | extends / modifies / depends on | ... |

---

## Open Questions

<!-- Anything unresolved. Each should have an owner if possible. -->
- [ ] Question 1 — *Owner: name*
- [ ] Question 2 — *Owner: name*
