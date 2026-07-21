---
type: Wiki Overview
title: 'TASK-1620: GigSmart GraphQL Documents'
id: doc:sdd-tasks-active-task-1620-gigsmart-graphql-documents-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: All GraphQL query and mutation strings for the GigSmart API. Organized by
  surface
relates_to:
- concept: mod:parrot_tools.interfaces.gigsmart
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.queries.engagements
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.queries.fragments
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.queries.gigs
  rel: mentions
---

# TASK-1620: GigSmart GraphQL Documents

**Feature**: FEAT-253 — GigSmart Interface Toolkit
**Spec**: `sdd/specs/gigsmart-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

All GraphQL query and mutation strings for the GigSmart API. Organized by surface
(locations, positions, gigs, engagements, timesheets, disputes, messages). Pure
string constants with no runtime dependencies. Implements Spec §2 Module 5.

---

## Scope

- Define GraphQL query strings for all 6 read surfaces (list + detail)
- Define GraphQL mutation strings for all write operations
- Use Relay pagination fragments (`edges { node { ... } } pageInfo { ... }`)
- Use the `$input` variable pattern for mutations (single variable)
- Write unit tests validating query structure (basic string assertions)

**NOT in scope**: HTTP execution (TASK-1621), Pydantic models (TASK-1619).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/queries/__init__.py` | CREATE | Package exports |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/queries/locations.py` | CREATE | Location queries |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/queries/positions.py` | CREATE | Position queries |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/queries/gigs.py` | CREATE | Gig queries + mutations |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/queries/engagements.py` | CREATE | Engagement queries + mutations |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/queries/timesheets.py` | CREATE | Timesheet queries + mutations |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/queries/messages.py` | CREATE | Message mutations |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/queries/fragments.py` | CREATE | Shared fragments (pageInfo, etc.) |
| `tests/tools/gigsmart/test_queries.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No framework imports needed — pure string constants
```

### Does NOT Exist
- ~~`gql` library~~ — do NOT import; use plain Python string constants
- ~~`graphql-core` query validation~~ — not needed; strings are validated at integration test time
- ~~`createLocation` mutation~~ — actual mutation is `addOrganizationLocation`
- ~~`createGig` / `postGig`~~ — actual mutation is `postShift`
- ~~`hireWorker` / `endEngagement` / `cancelEngagement`~~ — ALL state transitions use `transitionEngagement`
- ~~`editTimesheet`~~ — does NOT exist; only `approveTimesheet` and `removeTimesheetDispute`

---

## Implementation Notes

### Relay Pagination Pattern
All list queries MUST use Relay pagination:
```graphql
query ListGigs($first: Int, $after: String, $filter: GigFilter) {
  gigs(first: $first, after: $after, filter: $filter) {
    edges {
      node {
        id
        name
        ...
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

### Mutation Input Pattern
All mutations use a single `$input` variable:
```graphql
mutation PostShift($input: PostShiftInput!) {
  postShift(input: $input) {
    shift {
      id
      name
      ...
    }
  }
}
```

### Key Mutations (from schema introspection)
| Surface | Mutation Name | Input Type |
|---|---|---|
| Locations | `addOrganizationLocation` | `AddOrganizationLocationInput` |
| Locations | `placeAutocomplete` | `PlaceAutocompleteInput` |
| Positions | `addOrganizationPosition` | `AddOrganizationPositionInput` |
| Gigs | `postShift` | `PostShiftInput` |
| Gigs | `transitionGig` | `TransitionGigInput` |
| Engagements | `transitionEngagement` | `TransitionEngagementInput` |
| Timesheets | `approveTimesheet` | `ApproveTimesheetInput` |
| Timesheets | `removeTimesheetDispute` | `RemoveTimesheetDisputeInput` |
| Messages | `addConversationMessage` | `AddConversationMessageInput` |

### Key Queries (from schema introspection)
| Surface | Query Root | Key Fields |
|---|---|---|
| Gigs | `gigs` | id, name, startsAt, endsAt, slotsAvailable, gigState, payRate |
| Engagements | `node(id: $engagementId)` | id, currentStateName, workerName, gigId |
| Timesheets | embedded in engagement query | id, isApproved, totalDuration, billAmount |
| Organizations | `organizations` | id, name, locations, positions |
| Locations | embedded in org query | id, placeId, address, city, state |
| Positions | embedded in org query | id, name, category |

### Shared Fragment
Create a reusable `PAGE_INFO_FRAGMENT`:
```graphql
fragment PageInfoFields on PageInfo {
  hasNextPage
  hasPreviousPage
  startCursor
  endCursor
}
```

---

## Acceptance Criteria

- [ ] All 6 list queries use Relay edges/node pagination
- [ ] All mutations use single `$input` variable pattern
- [ ] Fragment for `PageInfo` is defined and referenced
- [ ] `transitionEngagement` is the ONLY engagement mutation (not per-action)
- [ ] `transitionGig` is the ONLY gig state-change mutation
- [ ] No reference to non-existent mutations (editTimesheet, createGig, hireWorker, etc.)
- [ ] Tests pass: `pytest tests/tools/gigsmart/test_queries.py -v`

---

## Test Specification

```python
import pytest
from parrot_tools.interfaces.gigsmart.queries.gigs import LIST_GIGS, POST_SHIFT
from parrot_tools.interfaces.gigsmart.queries.engagements import (
    LIST_ENGAGEMENTS, TRANSITION_ENGAGEMENT,
)
from parrot_tools.interfaces.gigsmart.queries.fragments import PAGE_INFO_FRAGMENT

class TestGraphQLDocuments:
    def test_list_gigs_uses_relay(self):
        assert "edges" in LIST_GIGS
        assert "node" in LIST_GIGS
        assert "pageInfo" in LIST_GIGS

    def test_post_shift_uses_input_var(self):
        assert "$input" in POST_SHIFT
        assert "PostShiftInput" in POST_SHIFT

    def test_transition_engagement_is_single_mutation(self):
        assert "transitionEngagement" in TRANSITION_ENGAGEMENT
        assert "$input" in TRANSITION_ENGAGEMENT

    def test_page_info_fragment_defined(self):
        assert "PageInfoFields" in PAGE_INFO_FRAGMENT
        assert "hasNextPage" in PAGE_INFO_FRAGMENT
        assert "endCursor" in PAGE_INFO_FRAGMENT

    def test_no_hallucinated_mutations(self):
        from parrot_tools.interfaces.gigsmart import queries
        all_queries_module = dir(queries)
        assert not any("editTimesheet" in str(getattr(queries, q, ""))
                       for q in all_queries_module)
```

---

## Completion Note

*(Agent fills this in when done)*
