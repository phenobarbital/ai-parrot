---
kind: file
jira_key: null
file_path: sdd/proposals/brainstorm-copilot-a2a-percredential.md
fetched_at: 2026-06-26T00:36:52Z
summary_oneline: Publish AI-Parrot as an A2A connected agent in M365 Copilot with parrot-owned per-user tool credential acquisition
---

# Source: Continuation of Copilot ⇄ A2A integration work

The user is continuing in-progress work integrating one AI-Parrot Agent into
Microsoft 365 Copilot via the Agent-to-Agent (A2A) protocol. The base artifact
is the brainstorm at `sdd/proposals/brainstorm-copilot-a2a-percredential.md`.

Key established facts from the brainstorm (full text preserved at
`source-original.md`):

- **Goal**: Make an AI-Parrot agent (bundling `work-iq`, `fireflies.ai`, `jira`
  tools) invokable from inside the M365 Copilot surface via Copilot Studio's
  A2A connection.
- **Closed decision**: Model B — credential custody stays in parrot (vault),
  not in Copilot's Power Platform connection store. Acquisition UX is link-out
  (OOB) to parrot's authenticated web surface.
- **Spike status (2026-06-26)**: Copilot connects + invokes parrot as an A2A
  sub-agent (POSTs `message/send` to host origin `/`, not the card `url`).
  AgentCard discovery still failing — name/description do NOT autopopulate.
- **Diagnosed root cause (§11)**: v0.3 vs v1.0 AgentCard schema fork + camelCase
  MUST + missing `supportedInterfaces`. Decision: dual-emit + camelCase. Fix
  lands in `parrot.a2a` model / `to_dict`, NOT `server.py`.
- **Hard part**: per-user tool authentication. `work-iq` (Entra OBO),
  `jira` (Atlassian 3LO), `fireflies` (static API key). A2A carries no user
  identity in the payload.
- **Spike gate (OQ#1)**: does Copilot's low-code A2A connection deliver a
  stable, verifiable per-user identity to parrot? The vault-keying premise
  depends on this.

The brainstorm carries two anchor classes: §11 anchors marked **VERIFIED**
against `examples/a2a/server.py`, and §7 anchors marked **⚠️ VERIFY** (the
credential/HITL/audit primitives). This proposal's job is to ground every one
of those anchors in the real codebase before any further spec work.
