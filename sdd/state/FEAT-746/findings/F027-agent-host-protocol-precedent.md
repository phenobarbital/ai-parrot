---
id: F027
query_id: Q019
type: read
intent: "Overlap: read the agent-host protocol proposal (any existing 'agent protocol' envelope/session-state design)."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 1
lane_origin: FW-013-agent-host-protocol-precedent
---

# F027 — FEAT-322 "agent-host-protocol" is an AHP-style dev-loop session-state design, not an inter-agent wire protocol; no naming collision, useful precedent for envelopes

## Summary

`sdd/proposals/agent-host-protocol-session-state.proposal.md` (FEAT-322, status review, confidence high, 2026-07-21) proposes mirroring Microsoft's Agent Host Protocol inside the dev-loop: `SessionHost` per run, frozen state tree, closed action union, channel-scoped `ActionEnvelope {channel, serverSeq, origin, rejectionReason}`, HITL gates. It is orchestration-internal (runner/dispatchers/streaming) and explicitly quarantines wire compatibility behind a future adapter because AHP is DRAFT. It neither defines nor reserves a cross-network agent-to-agent RPC, so the new protocol does not collide with it; its "mirror the invariant subset of a draft external spec" stance is a reusable precedent for how to treat A2A/MCP adapters. The structured-artifact brainstorm (FEAT-223, accepted) establishes the product direction "agents return structured objects; presentation decides rendering" — consistent with typed artifact descriptors.

## Citations

- path: `sdd/proposals/agent-host-protocol-session-state.proposal.md`
  lines: 1-60
  excerpt: |
    id: FEAT-322 — title: AHP-style multi-agent orchestration for dev-loop — session state, host, HITL gates — status: review
    "AHP is confirmed DRAFT, so wire compatibility stays quarantined behind a future adapter"
- path: `sdd/proposals/agent-host-protocol-session-state.proposal.md`
  lines: 60-120
  excerpt: |
    | parrot/flows/dev_loop/session_state.py | (new) | protocol-agnostic core: state/actions/reducers/SessionHost/shims |
    channel-scoped ActionEnvelope {channel, serverSeq, origin, rejectionReason}
- path: `sdd/proposals/structured-artifact-contract.brainstorm.md`
  lines: 1-60
  excerpt: |
    "agents return structured objects, and the presentation layer decides how to render them — with a data schema and a presentation schema"
    Status: accepted; Recommended Option: B (homologate the whole structured_ family)

## Notes

- No wiki memory/decision page about an agent-to-agent protocol, "Perch", or token-cost-of-tool-output was found (query "decision lesson agent-to-agent protocol remote agent token cost handles" returned only metrics/episodic pages) — this proposal would be the first durable record; worth a `wikitoolkit remember` once decided.
