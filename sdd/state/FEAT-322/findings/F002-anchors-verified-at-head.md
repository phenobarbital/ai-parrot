# F002 — Brainstorm code anchors re-verified at current HEAD (dev)

**Queries**: Q010 (grep), Q003/Q015 (wiki)
**Verified**: 2026-07-21, branch `dev` (post-FEAT-270 merge)
Paths relative to `packages/ai-parrot/src/`.

Every anchor from the brainstorm verifies EXACTLY — zero drift:

| Symbol | Location | Status |
|---|---|---|
| `class DevLoopRunner` | parrot/flows/dev_loop/runner.py:100 | ✅ exact |
| `conf.FLOW_MAX_CONCURRENT_RUNS` usage | runner.py:124 | ✅ exact |
| `class FlowEventPublisher` | flow.py:71 | ✅ exact |
| `FlowEventPublisher.__call__` | flow.py:94 | ✅ exact |
| `class FlowStreamMultiplexer` | streaming.py:51 | ✅ exact |
| `QANode._merge_manual_results` | nodes/qa.py:301 | ✅ exact |
| `QANode.execute` | nodes/qa.py:108 | ✅ |
| `class DeploymentHandoffNode` | nodes/deployment_handoff.py:46 | ✅ exact |
| `DeploymentHandoffNode.execute` | nodes/deployment_handoff.py:89 | ✅ exact |
| `class DevLoopNode` | nodes/base.py:152 | ✅ exact |
| `class ManualCriterion` | models.py:70 | ✅ exact |
| `class WorkBrief` | models.py:118 | ✅ exact |
| `WorkBrief.escalation_assignee` | models.py:161 | ✅ (field line now known) |
| `class QAReport` | models.py:349 | ✅ exact |
| `class DispatchEvent` | models.py:698 | ✅ exact |

Wiki pages consulted: `mod:parrot.flows.dev_loop.runner`,
`mod:parrot.flows.dev_loop.dispatcher`, streaming/task pages
(TASK-879 FlowStreamMultiplexer).
