---
kind: inline
jira_key: null
fetched_at: 2026-06-23T00:00:00Z
summary_oneline: "GigSmart interface toolkit: aiohttp REST client + GigSmartToolkit for LLM-driven API interaction"
---

## Source

Develop an aiohttp interface (on `parrot/tools/gigsmart/`) to interact with the GigSmart REST/GraphQL API, plus a `GigSmartToolkit` for LLM interaction with the GigSmart API.

### Key requirements:
1. **aiohttp-based HTTP client** for GigSmart API communication (REST + possible GraphQL)
2. **GigSmartToolkit** extending `WorkingMemoryToolkit` for agent tool exposure
3. **Pydantic v2 models** for all input/output validation
4. **DeterministicGuard** layer for write mutation safety
5. **WorkingMemory DataFrame** integration for large result sets

### External references:
- GigSmart Developer API docs: https://developers.gigsmart.ninja/docs/reference
- Existing brainstorm/spec: `sdd/proposals/GigSmartToolkit_SPEC.md`

### Functional surfaces (from brainstorm):
1. Authentication / session bootstrap
2. Location management (create, list, get)
3. Position management (create, list, get)
4. Gig posting (create, list, cancel)
5. Engagement management (list, hire, message, end)
6. Timesheet workflow (review, edit, approve, dispute response)

### Architecture notes (from brainstorm):
- Module: `parrot/tools/gigsmart/`
- Transport: `GigSmartGraphQLClient` using `aiohttp.ClientSession`
- Guard: `DeterministicGuard` with per-operation mandates
- Models: Pydantic v2 with camelCase aliases for API compatibility
