---
id: FEAT-708
title: "Addendum — /sdd-proposal parallel research reuses sdd-contract-probe"
type: feature
base_branch: dev
status: accepted
addendum_to: sdd/specs/sdd-proposal-parallel-research.spec.md
created: "2026-10-20"
projects: [sdd]
tags: [sdd-proposal, parallel-research, subagents, haiku, sdd-contract-probe]
---

# Addendum to FEAT-708 — reuse `sdd-contract-probe` for code fact-checks

> **For whoever writes or implements the FEAT-708 spec**
> (`sdd-proposal-parallel-research`). When this addendum was written, FEAT-708
> was reserved in `sdd/tasks/.id_ledger.json` (commit 9d6a6ed4a), but its spec
> was not on `dev` yet. `/sdd-spec` does not auto-load `*.addendum.md`: fold
> the decision below into the spec (Section 6 / Codebase Contract and the
> research-lane design) when you write it.

## Decision

`/sdd-proposal`'s parallel research lanes MUST NOT define their own
fact-checking subagent. For every **flat, deterministic check against the
code**, they reuse the agent `/sdd-task` got in PR #1742:

- **Agent**: `.claude/agents/sdd-contract-probe.md` (Haiku; Read/Grep/Glob/Bash; read-only).
- **Check kinds**: `symbol` (exists + verbatim signature), `import` (module
  resolves, symbol defined or re-exported), `anchor` (occurrence count + line
  numbers), `absent` (a name is really absent from a whole module), `sha256`,
  `outline` (a file's `def`/`class` list).
- **Report**: one JSON object. Each result carries the exact command, its
  raw output, `count`, `lines`, `signature`, and the `HEAD` it ran against,
  so the caller can re-run any line.

## Why

- **One instrument, one contract.** `/sdd-task` already verifies these
  reports (HEAD match; re-runs every negative/ambiguous result plus one
  `found` in ten; discards a report that does not reproduce). If
  `/sdd-proposal` reused a different agent, it would have to define and test
  a second set of rules for the same job.
- **Fixed commands, no truncating filters.** The repo has been burned by a
  `grep | head` cut-off that recorded a false "X does not exist" in a
  committed SDD doc. The probe bans `| head`/`| tail`/`-m` and scopes
  `absent` checks to the whole module.
- **Cost.** Smoke test: 7/7 checks correct against hand-run ground truth,
  about 77K Haiku tokens in 30 s, almost all of it fixed startup cost. Groups
  of about 40 checks per probe amortize it.

## How it fits the research lanes

1. Research lanes keep doing the *open* work: reading code to understand a
   subsystem and writing finding digests. That needs judgement, so it is not
   a probe job.
2. When a lane, or the synthesis step, is about to **assert a code fact** in
   the proposal ("`X` exists with signature …", "`Y` does not exist", "anchor
   `Z` is at `path:NN`"), it collects the fact as a probe check instead of
   asserting it from memory.
3. The orchestrator dedupes the checks across lanes, launches the probes in
   parallel in one message, and applies the **same verification rules as
   `/sdd-task` §3**, *Delegating flat checks to `sdd-contract-probe`*. Only
   verified facts get confidence `high` in the proposal.
4. If no `Agent` tool is available (dev-loop, Codex), or there are fewer than
   ~10 checks, run the checks inline. The rules are the same.

## Out of scope

- Changing `sdd-contract-probe`'s check kinds or output schema. If FEAT-708
  needs a new kind, add it to the agent, where `/sdd-task` gets it as well.
  Do not fork the agent.
- Delegating judgement (what to research, what a finding means, the
  recommendation) to the probe.
