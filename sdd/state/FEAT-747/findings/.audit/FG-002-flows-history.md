---
id: FG-002
query_id: Q051
type: git_log
intent: "Recent activity on bots/flows (crew + flow + core) — active development area per CONTEXT.md."
executed_at: 2026-10-25T22:41:00Z
duration_ms: 350
parent_id: null
depth: 0
---

# FG-002 — bots/flows history (90 days): FEAT-590 tool-call-delegate (plan nodes), crew credential plumbing, FEAT-524 history ownership

## Summary

~40 commits since 2026-08-01, authors Jesus / Jesus Lara / revbot. Dominant theme (Sep 23): **FEAT-590 tool-call-delegate** — `DelegateToolNode`, `PlanToolNode` invoke-hook refactor, `LlamaCppDelegate` / `NeedleDelegate` backends, plan-language discriminated union (TASK-3626..3633). This is *tool-call planning delegated to a small local model*, not agent-to-agent messaging. Second theme (Sep 19): FEAT-575 `AgentCrew.__init__(google_api_key=)` credential injection. Also: FEAT-524 "bot callers render history, pass history=, single writer" (Sep 4), TASK-2991 "preserve plan and tee artifact provenance after dispatch" (Sep 8, WorkingMemory ↔ flows), Oct 2 resolver routing of `discover_from_registry` callers, Oct 22 TASK-4617 configure-site guards. No commit touches inter-agent messaging semantics, performatives, or a shared blackboard.

## Citations

- sha: `ae7ebda977` date: 2026-10-22 author: Jesus Lara — feat(bots-agent-tech-debt): TASK-4617 — guard the nine post-super configure sites
- sha: `c3bb61eaf7` date: 2026-10-18 author: Jesus — fix(crew): HOTFIX — honor all four Google credential signals in AgentCrew.__init__
- sha: `6ffbeadee5` date: 2026-10-02 author: revbot — feat(agentstudio-host-toolkits): route remaining discover_all/discover_from_registry callers through the resolver
- sha: `4b15dbc4ae` date: 2026-09-23 author: Jesus — feat(tool-call-delegate): TASK-3631 — DelegateToolNode + factory
- sha: `314aee865e` date: 2026-09-23 author: Jesus — feat(tool-call-delegate): TASK-3633 — NeedleDelegate backend
- sha: `4ec6e7ad30` date: 2026-09-23 author: Jesus — feat(tool-call-delegate): TASK-3632 — LlamaCppDelegate backend
- sha: `22415cc7ba` date: 2026-09-23 author: Jesus — feat(tool-call-delegate): TASK-3630 — PlanToolNode invoke-hook refactor
- sha: `8c967dd9be` date: 2026-09-23 author: Jesus — feat(tool-call-delegate): TASK-3626 — plan-language discriminated union
- sha: `ca2ab5f7c1` date: 2026-09-22 author: Jesus — fix: fire required checkpoint barrier in definition-driven scheduler mode
- sha: `2af1f4eb4b` date: 2026-09-19 author: Jesus — feat(agentcrew-handler-default-key): TASK-3454 — from_definition(google_api_key=) injection + forwarding
- sha: `03e9a7cf51` date: 2026-09-17 author: Jesus Lara — feat(crew): configurable infographic theme on CrewDefinition/AgentCrew
- sha: `8ae42e6131` date: 2026-09-08 author: Jesus Lara — feat(workingmemory-toolkit): TASK-2991 — preserve plan and tee artifact provenance after dispatch
- sha: `668e2521a4` date: 2026-09-04 author: Jesus — feat(conversation-history-ownership): TASK-2816 — bot callers render history, pass history=, single writer
- path: `sdd/specs/tool-call-delegate.spec.md`
  lines: 8-20
  symbol: `FEAT-590`
  excerpt: |
    # Feature Specification: Tool-Call Delegate
    (Modules: delegate protocol, AbstractTool delegate flags, plan-language union,
     DelegateToolNode + factory, LlamaCppDelegate, NeedleDelegate, toolkit + planner wiring)

## Notes

- FEAT-590's "delegate" is a *small-model tool-call planner*, not inter-agent delegation — the brainstorm's `delegate` tool name would collide in vocabulary; the spec should pick another word or state the distinction.
- TASK-2991 shows flows already tee *artifact provenance* into WorkingMemory after dispatch — a seam for "result lands as native object with provenance".
- [cross-lane: type=grep, intent=locate the TASK-2991 provenance tee in bots/flows (grep 'provenance' under bots/flows and tools/working_memory)]
