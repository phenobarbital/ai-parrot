---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Codex CLI Adversarial Second-Opinion Agent

**Feature ID**: FEAT-375
**Date**: 2026-07-26
**Author**: Jesus Lara (proposal research + Q&A: /sdd-proposal FEAT-375)
**Status**: approved
**Target version**: next dev release
**Proposal**: `sdd/proposals/codex-cli-agent.proposal.md` (research audit: `sdd/state/FEAT-375/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev loop already invokes the OpenAI `codex` CLI as a sub-agent: codex is a
selectable development-worker backend in the `DevAgentPool` (FEAT-323) and a
selectable QA code reviewer (FEAT-270, `DEV_LOOP_CODEREVIEW_AGENT=codex`).
However, the existing codex reviewer is **write-enabled** — it fixes issues it
finds and commits to the worktree branch. There is no way to use codex as an
**adversarial second opinion**: a read-only, advisory reviewer that receives a
*neutral brief* (diff + requirement + question — never the primary agent's
reasoning, which would produce ratification instead of review) and whose
findings are explicitly triaged by the primary worker as **CONFIRM** (fix),
**REJECT** (record why), or **ESCALATE** (human decides) — never silently
conceded, never silently dropped.

### Goals

- **G1 — Advisory reviewer**: a `codex-adversarial` code-review dispatcher that
  runs codex in a read-only sandbox, emits findings only (never modifies
  files), and coexists with the write-enabled `codex` entry unchanged.
- **G2 — Neutral brief**: a new `sdd-secondopinion` subagent definition whose
  brief carries the diff, the requirements, and the review question only —
  by construction it cannot include the primary agent's reasoning.
- **G3 — Triage loop**: QANode routes advisory findings to the **primary
  worker**, which must assign every finding a disposition
  (CONFIRM/REJECT/ESCALATE); confirmed fixes re-enter the existing
  deterministic-QA rerun path.
- **G4 — Escalation**: ESCALATE opens a blocking FEAT-322 HITL gate **and**
  records the finding in the QA report notes (which surface in the PR body).
- **G5 — Review targets**: support `codex exec review` scopes — uncommitted
  changes (default), `--base <ref>`, `--commit <sha>`.
- **G6 — Session continuation**: support `codex exec resume --last
  "<question>"` follow-ups within one review conversation.
- **G7 — Parallel perspective**: a composite reviewer that runs the primary
  (write-enabled) reviewer and the codex adversary concurrently on the same
  neutral brief and synthesizes agreements/disagreements deterministically,
  with an optional config-gated LLM-judge pass.

### Non-Goals (explicitly out of scope)

- Reworking `CodexCodeDispatcher` internals (event streaming, semaphore,
  worktree guard) — all changes are additive.
- Changing the behavior of the existing `codex`, `claude-code`, or `gemini`
  review dispatchers.
- Image generation (`image_gen`) — no dev-loop consumer; deferred.
- The FEAT-374 devloop CLI console (in-flight, separate feature).
- Making the advisory path available outside the dev loop (e.g., as a
  standalone `parrot.tools` tool).

---

## 2. Architectural Design

### Overview

Everything lands on the FEAT-270 extension seam. A new
`CodexAdversarialReviewDispatcher` registers as `"codex-adversarial"` in
`CodeReviewDispatcherFactory` (coexisting with `"codex"` — resolved U1).
It reuses the existing `CodexCodeDispatcher.dispatch()` machinery with a new
`CodexAdversarialReviewProfile`: `sandbox="read-only"`,
`subagent="sdd-secondopinion"`, and review-target fields that make
`_build_command()` emit `codex exec review` command shapes (G5) or
`codex exec resume --last` continuations (G6).

The advisory verdict never carries `files_modified`. Instead, QANode detects
an advisory reviewer (class attribute `advisory = True`) and, when findings
exist, dispatches the **primary development dispatcher** (the same
`ClaudeCodeDispatcher` QANode already holds) with a `TriageBrief`; the worker
returns a `TriageReport` assigning every finding a disposition (resolved U2).
CONFIRM fixes → `files_modified` → the existing deterministic-QA rerun.
ESCALATE → `SessionHost.open_gate(kind="review_escalation", ...)` (new
`GateKind` value, fail-closed TTL) + a note appended to `QAReport.notes`
(resolved spec-round Q: gate **and** PR note).

Parallel perspective (G7) is a fourth registry entry, `"parallel"`: a
composite dispatcher that `asyncio.gather`s the primary reviewer and the
codex adversary, merges verdicts deterministically (union of findings, each
tagged with its source(s); agreement = same file + normalized message), and —
only when `DEV_LOOP_CODEREVIEW_JUDGE=true` — adds an LLM-judge dispatch that
writes a synthesis narrative (resolved spec-round Q: deterministic + optional
judge).

### Component Diagram

```
QANode.execute()
  ├── _run_deterministic_qa()  (existing, unchanged)
  └── _run_code_review()  → CodeReviewDispatcherFactory entry:
        ├── "claude-code" | "codex" | "gemini"      (existing, write-enabled)
        ├── "codex-adversarial"  (NEW, advisory)
        │      └── CodexCodeDispatcher.dispatch(CodexAdversarialReviewProfile)
        │             └── codex exec review … --sandbox read-only
        └── "parallel"  (NEW, composite)
               ├── primary reviewer (write-enabled)   ─┐ asyncio.gather
               ├── codex-adversarial (advisory)       ─┘
               ├── deterministic merge (always)
               └── LLM judge dispatch (only if DEV_LOOP_CODEREVIEW_JUDGE)

  advisory findings present?
        └── _run_finding_triage()  (NEW)
               └── primary dev dispatcher (sdd-worker) ← TriageBrief
                      └── TriageReport: per finding CONFIRM/REJECT/ESCALATE
                            ├── CONFIRM → fixes committed → deterministic rerun
                            ├── REJECT  → reason recorded in QAReport.notes
                            └── ESCALATE → SessionHost.open_gate("review_escalation")
                                           + note in QAReport.notes → PR body
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CodeReviewDispatcherFactory` (`code_review.py:104`) | extends (2 new registrations) | `"codex-adversarial"`, `"parallel"` |
| `CodexCodeDispatcher` (`dispatcher.py:936`) | uses + extends `_build_command` | new `exec review` / `exec resume` command shapes, profile-driven |
| `CodexCodeDispatchProfile` (`models.py:540`) | subclasses | `CodexAdversarialReviewProfile` |
| `QANode` (`nodes/qa.py:147-221`) | extends | advisory detection + `_run_finding_triage()`; reuses rerun path at `qa.py:164-173` |
| `load_subagent_definition` (`_subagent_defs.py:62`) | extends `_VALID_NAMES` | add `"sdd-secondopinion"` |
| `SessionHost.open_gate` (`session_state.py:861`) | uses | new `GateKind` value `"review_escalation"` |
| `build_dev_loop_node_factories` (`factories.py:53,140`) | unchanged signature | any `AbstractCodeReviewDispatcher` already flows through |
| `parrot/conf.py` (`:923-932`) | extends | new envs; append-only (FEAT-374 conflict risk, §7) |

### Data Models

```python
# parrot/flows/dev_loop/models.py — NEW (design-level, exact fields for tasks)

class CodexAdversarialReviewProfile(CodexCodeDispatchProfile):
    """Advisory review profile — read-only, neutral-brief, no writes."""
    subagent: Literal["sdd-secondopinion"] = "sdd-secondopinion"
    sandbox: Literal["read-only"] = "read-only"
    approval_policy: Literal["never"] = "never"
    review_scope: Literal["uncommitted", "base", "commit"] = "uncommitted"
    review_base: str = ""        # used when review_scope == "base"
    review_commit: str = ""      # used when review_scope == "commit"
    resume_last: bool = False    # G6: codex exec resume --last continuation
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)

class AdversarialFinding(CodeReviewFinding):
    """A finding awaiting or carrying a triage disposition."""
    source: str = "codex-adversarial"   # reviewer that produced it
    disposition: Optional[Literal["confirm", "reject", "escalate"]] = None
    triage_reason: str = ""

class TriageBrief(BaseModel):
    """Brief for the primary worker's triage dispatch (neutral: findings only)."""
    findings: List[AdversarialFinding]
    acceptance_criteria: List[AcceptanceCriterion]
    worktree_path: str
    summary: str = ""

class TriageReport(BaseModel):
    """Every input finding MUST appear with a disposition — none dropped."""
    findings: List[AdversarialFinding]       # disposition set on each
    files_modified: List[str] = Field(default_factory=list)  # from CONFIRM fixes
    summary: str = ""

class PerspectiveSynthesis(BaseModel):
    """Deterministic merge of primary + adversarial verdicts (G7)."""
    agreements: List[AdversarialFinding]     # flagged by BOTH reviewers
    disagreements: List[AdversarialFinding]  # flagged by exactly one (source set)
    judge_summary: str = ""                  # filled only by optional LLM judge
```

`GateKind` (`session_state.py:166`) gains one value: `"review_escalation"`.

### New Public Interfaces

```python
# parrot/flows/dev_loop/code_review.py

@CodeReviewDispatcherFactory.register("codex-adversarial")
class CodexAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):
    agent_name = "codex-adversarial"
    advisory = True   # NEW class attribute; False (default) on the ABC

    def __init__(self, *, dispatcher: CodexCodeDispatcher,
                 model: str | None = None,
                 review_scope: str = "uncommitted", ...) -> None: ...
    def build_review_profile(self) -> CodexAdversarialReviewProfile: ...

@CodeReviewDispatcherFactory.register("parallel")
class ParallelPerspectiveReviewDispatcher(AbstractCodeReviewDispatcher):
    agent_name = "parallel"
    advisory = True   # its merged residue is triaged like advisory findings

    def __init__(self, *, primary: AbstractCodeReviewDispatcher,
                 adversary: AbstractCodeReviewDispatcher,
                 judge_dispatcher: Optional[Any] = None) -> None: ...
    async def review(self, ...) -> CodeReviewVerdict:
        """gather(primary, adversary) → deterministic merge → optional judge."""
```

---

## 3. Module Breakdown

### Module 1: Models & GateKind
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
- **Responsibility**: `CodexAdversarialReviewProfile`, `AdversarialFinding`,
  `TriageBrief`, `TriageReport`, `PerspectiveSynthesis`; widen
  `CodexCodeDispatchProfile.subagent` to
  `Literal["sdd-worker", "sdd-secondopinion"]` (default unchanged); add
  `"review_escalation"` to `GateKind`.
- **Depends on**: — (first)

### Module 2: `sdd-secondopinion` subagent brief
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-secondopinion.md`,
  `.claude/agents/sdd-secondopinion.md` (dual-sourced, FEAT-323 pattern),
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py`
- **Responsibility**: neutral adversarial persona (diff + requirements +
  question only; advisory output; findings must be specific and falsifiable);
  extend `_VALID_NAMES` (`_subagent_defs.py:32-34`). NOTE: `git add -f` needed
  only for `sdd/templates/`, not here.
- **Depends on**: —

### Module 3: Dispatcher command variants
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py`
- **Responsibility**: extend `CodexCodeDispatcher._build_command()`
  (`dispatcher.py:1119-1151`) with table-driven branches:
  (a) `review_scope` → `codex exec review [--base <ref>|--commit <sha>]`
  variants; (b) `resume_last` → `codex exec resume --last` (gotcha: `resume`
  does NOT accept `--sandbox`; pass `-c sandbox_mode="read-only"`). Verify the
  installed CLI's flag support for `--json`/`--output-schema` under `review`
  at implementation time; if unsupported, fall back to `exec --json` with the
  diff embedded in the prompt (behavior identical from the caller's view).
- **Depends on**: Module 1

### Module 4: Advisory + parallel review dispatchers
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`
- **Responsibility**: `CodexAdversarialReviewDispatcher` ("codex-adversarial")
  and `ParallelPerspectiveReviewDispatcher` ("parallel") with deterministic
  merge (agreement key: `file` + case/whitespace-normalized `message`) and
  optional judge pass; `advisory: bool = False` attribute on the ABC.
  Both inherit the degrade-on-infra-error contract (`code_review.py:85-97`).
- **Depends on**: Modules 1, 3

### Module 5: QANode triage loop
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`
- **Responsibility**: after `_run_code_review()` (`qa.py:157`), when the
  dispatcher is `advisory` and findings exist → `_run_finding_triage()`:
  dispatch the primary dev dispatcher (`self` already holds it, `qa.py:92-103`)
  with `TriageBrief` → `TriageReport`; CONFIRM fixes reuse the existing
  `files_modified` rerun (`qa.py:164-173`); REJECT reasons appended to
  `QAReport.notes`; ESCALATE opens
  `SessionHost.open_gate(kind="review_escalation", on_expiry="fail")` and
  appends a PR-visible note. Validation: every input finding must return with
  a disposition, else the triage dispatch is retried once and then treated as
  ESCALATE (fail-closed).
- **Depends on**: Modules 1, 4

### Module 6: Config & wiring
- **Path**: `packages/ai-parrot/src/parrot/conf.py`,
  `examples/dev_loop/server.py`
- **Responsibility**: accept `"codex-adversarial"` / `"parallel"` in
  `DEV_LOOP_CODEREVIEW_AGENT` (`conf.py:930-932`); new envs:
  `DEV_LOOP_CODEREVIEW_JUDGE` (bool, default False),
  `DEV_LOOP_ADVERSARIAL_MODEL` (default `"gpt-5.5"`),
  `DEV_LOOP_ADVERSARIAL_SCOPE` (default `"uncommitted"`),
  `DEV_LOOP_GATE_TTL_REVIEW_ESCALATION` (default 86400, fail-closed).
  **Append-only additions at the end of the dev-loop conf section** (FEAT-374
  has in-flight edits to conf.py — §7 risk).
- **Depends on**: Modules 4, 5

### Module 7: Tests
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/`
- **Responsibility**: unit + integration tests (see §4), mirroring
  `test_code_review.py` (multi-dispatcher gate) and `test_qa_codereview.py`
  (QANode gate) patterns.
- **Depends on**: Modules 1-6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_adversarial_profile_defaults` | 1 | read-only sandbox, sdd-secondopinion subagent, approval never |
| `test_gatekind_review_escalation` | 1 | new literal value accepted by `open_gate` |
| `test_secondopinion_brief_loads` | 2 | `load_subagent_definition("sdd-secondopinion")` returns body, frontmatter stripped |
| `test_secondopinion_unknown_name_still_raises` | 2 | `ValueError` for names outside `_VALID_NAMES` |
| `test_build_command_review_uncommitted` | 3 | command shape for default scope |
| `test_build_command_review_base_and_commit` | 3 | `--base` / `--commit` variants |
| `test_build_command_resume_no_sandbox_flag` | 3 | resume uses `-c sandbox_mode=...`, never `--sandbox` |
| `test_adversarial_dispatcher_registered` | 4 | factory creates `"codex-adversarial"`; `advisory is True` |
| `test_adversarial_verdict_never_modifies_files` | 4 | `files_modified == []` enforced |
| `test_parallel_merge_agreement_detection` | 4 | same file+normalized message → agreement, tagged both sources |
| `test_parallel_judge_only_when_flag` | 4 | judge dispatch not called when `DEV_LOOP_CODEREVIEW_JUDGE=false` |
| `test_parallel_degrades_on_one_failure` | 4 | one reviewer failing → other's verdict + nit finding |
| `test_qanode_triage_all_dispositions` | 5 | CONFIRM→rerun, REJECT→notes, ESCALATE→gate+notes |
| `test_qanode_triage_missing_disposition_fails_closed` | 5 | undispositioned finding → retry once → escalate |
| `test_qanode_non_advisory_path_unchanged` | 5 | `"codex"` (write-enabled) behavior byte-identical |
| `test_conf_new_envs_defaults` | 6 | defaults as specified |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_adversarial_review_triage` | fake codex binary emits findings → QANode triage → CONFIRM fix path reruns deterministic QA |
| `test_e2e_escalation_opens_gate_and_pr_note` | ESCALATE → `review_escalation` gate pending + note in `QAReport.notes` |
| `test_e2e_parallel_perspective` | primary + adversary stubs → merged verdict with agreements/disagreements |

### Test Data / Fixtures

Reuse the fake-CLI-binary pattern from `tests/flows/dev_loop/test_code_review.py`
(stub `codex` executable writing a canned JSON verdict to the `-o` path);
fixtures for `AdversarialFinding` lists with known agreement overlaps.

---

## 5. Acceptance Criteria

- [ ] `CodeReviewDispatcherFactory.create("codex-adversarial", ...)` returns an
      advisory dispatcher; `create("codex", ...)` behavior is unchanged
      (existing FEAT-270 tests still pass untouched).
- [ ] Advisory dispatches run with `sandbox="read-only"` and never report
      `files_modified` — enforced in code, covered by test.
- [ ] The `sdd-secondopinion` brief contains only diff/requirements/question
      placeholders — no field exists for caller reasoning (G2, by construction).
- [ ] Every advisory finding receives a disposition in the `TriageReport`;
      missing dispositions fail closed to ESCALATE (never silently dropped).
- [ ] ESCALATE opens a `review_escalation` gate (fail-closed,
      `DEV_LOOP_GATE_TTL_REVIEW_ESCALATION`) AND appends a note to
      `QAReport.notes`.
- [ ] `codex exec review` scopes (uncommitted/base/commit) and
      `resume --last` command shapes are table-driven and unit-tested;
      `resume` never receives `--sandbox`.
- [ ] `"parallel"` merges deterministically (agreements tagged with both
      sources); the LLM judge runs only when `DEV_LOOP_CODEREVIEW_JUDGE=true`.
- [ ] Degrade-on-infra-error (FEAT-250 G4) holds for both new dispatchers.
- [ ] All new and existing tests pass:
      `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No breaking changes to the public API (`parrot.flows.dev_loop`
      `__init__` exports only gain names).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All line numbers verified
> 2026-07-26 on `dev` @ `ec6e0432a`.

### Verified Imports

```python
from parrot.flows.dev_loop.code_review import (      # code_review.py:191-197 (__all__)
    AbstractCodeReviewDispatcher,                    # code_review.py:35
    CodeReviewDispatcherFactory,                     # code_review.py:104
    CodexCodeReviewDispatcher,                       # code_review.py:152
)
from parrot.flows.dev_loop.dispatcher import CodexCodeDispatcher   # dispatcher.py:936
from parrot.flows.dev_loop.models import (
    CodeReviewFinding,                               # models.py:739
    CodeReviewVerdict,                               # models.py:748
    CodexCodeDispatchProfile,                        # models.py:540
    CodexCodeReviewProfile,                          # models.py:797
    AcceptanceCriterion,                             # used by qa.py:33-42 imports
)
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition  # _subagent_defs.py:62
from parrot.flows.dev_loop.session_state import SessionHost, GateKind      # session_state.py:861,166
```

### Existing Class Signatures

```python
# dispatcher.py
class CodexCodeDispatcher:                                        # line 936
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int, codex_bin: str = "codex") -> None  # 951-958
    async def dispatch(self, *, brief: BaseModel,
                       profile: CodexCodeDispatchProfile,
                       output_model: Type[T], run_id: str, node_id: str,
                       cwd: str, session_host: Optional[SessionHost] = None) -> T  # 968-978
    def _build_command(self, *, profile, cwd, schema_path,
                       output_path, prompt) -> List[str]          # 1119-1151
        # emits: codex exec --json --cd <cwd> --model <m> --sandbox <s>
        #        --ask-for-approval <p> --output-schema <f> -o <f>
        #        [--ignore-user-config] [--ignore-rules] <prompt>
    def _build_codex_prompt(self, profile, brief, output_model) -> str  # 1153-1165
        # loads load_subagent_definition(profile.subagent) as preamble
    def _validate_output_file(self, output_path, output_model) -> T     # 1238-1262
    def _enforce_cwd_under_worktree_base(self, cwd: str) -> None        # 1264
        # every dispatch cwd MUST resolve under conf.WORKTREE_BASE_PATH

# code_review.py
class AbstractCodeReviewDispatcher(ABC):                          # line 35
    agent_name: str                                               # 49
    async def review(self, *, brief: BaseModel, run_id: str, node_id: str,
                     cwd: str, session_host: Optional[SessionHost] = None
                     ) -> CodeReviewVerdict                       # 51-97
        # delegates to self._dispatcher.dispatch(profile=self.build_review_profile(),
        #                                        output_model=CodeReviewVerdict)
        # degrade-on-infra-error: returns passed=True + nit finding  # 85-97
    @abstractmethod
    def build_review_profile(self) -> BaseModel                   # 99-101

class CodeReviewDispatcherFactory:                                # 104
    @classmethod register(cls, name: str)                         # 109-117 (decorator)
    @classmethod create(cls, name: str, **kwargs)                 # 119-127

@CodeReviewDispatcherFactory.register("codex")
class CodexCodeReviewDispatcher(AbstractCodeReviewDispatcher):    # 151-168
    def __init__(self, *, dispatcher: CodexCodeDispatcher,
                 model: str | None = None) -> None                # 162 (default "gpt-5.5")

# models.py
class CodexCodeDispatchProfile(BaseModel):                        # 540
    subagent: Literal["sdd-worker"] = "sdd-worker"                # 548  ← MUST widen
    model: str = "gpt-5.5"                                        # 549
    sandbox: Literal["read-only", "workspace-write",
                     "danger-full-access"] = "workspace-write"    # 550 ("read-only" already valid)
    approval_policy: Literal["untrusted", "on-request", "never"] = "never"  # 551
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)    # 552
    ignore_user_config: bool = True                               # 553
    ignore_rules: bool = False                                    # 560

class CodeReviewFinding(BaseModel):                               # 739
    message: str; severity: Literal["critical","major","minor","nit"]
    file: str = ""; line: int = 0                                 # 742-745

class CodeReviewVerdict(BaseModel):                               # 748
    passed: bool = True; findings: List[CodeReviewFinding]
    summary: str = ""; files_modified: List[str]                  # 760-763
    # findings validator coerces plain strings → minor findings   # 765-775

# nodes/qa.py
class QANode:  # __init__ param                                   # 92-103
    codereview_dispatcher: Optional[AbstractCodeReviewDispatcher] = None
    # None → defaults to ClaudeCodeReviewDispatcher(dispatcher=dispatcher)  # 101-102
    # stored as self._codereview_dispatcher via object.__setattr__          # 103
# gate sequencing in execute():                                   # 147-221
#   _run_code_review returns (passed, findings: List[str], files_modified)  # 282-320
#   files_modified truthy → deterministic QA re-runs               # 164-173
#   _CODE_REVIEW_SKIP_PREFIX = "code-review could not run:"        # 51
class _CodeReviewBrief(BaseModel):  # brief passed to reviewers    # (qa.py, after :51)
    acceptance_criteria: List[AcceptanceCriterion]
    worktree_path: str; summary: str = ""; jira_issue_key: str = ""

# _subagent_defs.py
_VALID_NAMES = frozenset({"sdd-research","sdd-worker","sdd-qa","sdd-codereview"})  # 32-34 ← MUST extend
def load_subagent_definition(name: str) -> str                    # 62-86
# briefs dual-sourced: .claude/agents/<name>.md + _subagent_data/<name>.md  # 13-20

# session_state.py
GateKind = Literal["manual_criterion","deployment_approval",
                   "revision_approval","plan_approval"]           # 166-171 ← MUST extend
class SessionHost:
    def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str,
                  instructions: str = "", payload_ref: str = "",
                  ttl_seconds: Optional[int] = None,
                  on_expiry: Literal["fail","approve"] = "fail"
                  ) -> Tuple[str, ActionEnvelope]                 # 861-871

# factories.py
def build_dev_loop_node_factories(*, dispatcher, jira_toolkit, redis_url,
    development_dispatcher=None, development_profile=None,
    development_pool_config=None, development_dispatcher_builder=None,
    development_pool_max: int = 4, codereview_dispatcher=None, ...)  # 43-53
    # codereview_dispatcher flows into QANode                        # 140

# conf.py
DEV_LOOP_CODEREVIEW_MODEL  # :924-926, default "claude-sonnet-4-6"
DEV_LOOP_CODEREVIEW_AGENT  # :930-932, default "claude-code"
# gate TTL conf pattern to copy: DEV_LOOP_GATE_TTL_* # :961-972

# agent_builder.py — codex dev-worker branch (do not touch)
# spec.agent == "codex" → CodexCodeDispatcher + profile(DEV_LOOP_CODEX_MODEL)  # 143-146
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CodexAdversarialReviewDispatcher` | `CodeReviewDispatcherFactory.register` | decorator | `code_review.py:109-117` |
| `CodexAdversarialReviewProfile` | `CodexCodeDispatcher.dispatch(profile=...)` | param | `dispatcher.py:968-978` |
| `exec review` command shapes | `CodexCodeDispatcher._build_command` | extension | `dispatcher.py:1119-1151` |
| `sdd-secondopinion` brief | `_build_codex_prompt` → `load_subagent_definition` | name lookup | `dispatcher.py:1159`, `_subagent_defs.py:78-86` |
| `_run_finding_triage()` | QANode gate flow after `_run_code_review` | new call site | `nodes/qa.py:157-173` |
| ESCALATE gate | `SessionHost.open_gate(kind="review_escalation")` | method call | `session_state.py:861-871` |
| `ParallelPerspectiveReviewDispatcher` | wraps two `AbstractCodeReviewDispatcher.review()` | `asyncio.gather` | `code_review.py:51-97` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.flows.devloop`~~ — the package is `parrot/flows/dev_loop/`
  (underscore); `parrot/cli/devloop/` is the FEAT-374 console, NOT this seam.
- ~~`codex exec review` / `codex exec resume` usage~~ — zero call sites in the
  codebase today (grep-verified); Module 3 creates them.
- ~~`--skip-git-repo-check`~~ — flag from the request's example; not used
  anywhere and NOT needed (dispatches run inside git worktrees).
- ~~`CodeReviewDispatcherFactory` entry `"codex-adversarial"` / `"parallel"`~~
  — do not exist yet (registry has exactly: claude-code, codex, gemini).
- ~~`sdd-secondopinion` in `_VALID_NAMES` or `_subagent_data/`~~ — must be added.
- ~~`GateKind` value `"review_escalation"`~~ — must be added.
- ~~`TriageBrief` / `TriageReport` / `AdversarialFinding` / `PerspectiveSynthesis`~~
  — new models, do not import until Module 1 lands.
- ~~`conf.DEV_LOOP_CODEREVIEW_JUDGE` / `DEV_LOOP_ADVERSARIAL_MODEL` /
  `DEV_LOOP_ADVERSARIAL_SCOPE` / `DEV_LOOP_GATE_TTL_REVIEW_ESCALATION`~~ — new.
- ~~`advisory` attribute on `AbstractCodeReviewDispatcher`~~ — new in Module 4.
- ~~`AbstractCodeReviewDispatcher.review()` accepting a triage callback~~ —
  triage lives in QANode, not the dispatcher ABC.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Factory registration decorator exactly as FEAT-270's three reviewers
  (`code_review.py:130-188`).
- Profile-subclass-overrides-defaults (`CodexCodeReviewProfile`,
  `models.py:797-809`) for the adversarial profile.
- Dual-sourced subagent briefs (repo `.claude/agents/` + package
  `_subagent_data/`), FEAT-323 precedent (`_subagent_defs.py:13-20`).
- Gate TTL conf naming (`DEV_LOOP_GATE_TTL_*`, `conf.py:961-972`).
- Fake-CLI-binary test pattern from `tests/flows/dev_loop/test_code_review.py`.
- Async throughout; `self.logger`; Pydantic for all structured data.

### Known Risks / Gotchas

- **Codex CLI surface drift**: `codex exec review` flag support for
  `--json`/`--output-schema` must be verified against the installed CLI during
  Module 3; fall back to `exec --json` with the diff embedded in the prompt if
  unsupported. Keep command shapes table-driven + unit-tested.
- **`resume` sandbox gotcha**: `codex exec resume` does NOT accept
  `--sandbox`; pass `-c sandbox_mode="read-only"` (source-verified behavior
  from the request author's usage).
- **conf.py merge conflict**: FEAT-374 has uncommitted in-flight edits to
  `parrot/conf.py`, `parrot/cli/devloop/bootstrap.py`, `parrot/cli/wizard.py`.
  Add new settings append-only at the end of the dev-loop section; do NOT
  reflow existing lines.
- **Triage loop cost**: one extra worker dispatch per review round with
  findings; bounded — triage runs at most once per QA pass plus one retry on
  missing dispositions (fail-closed to ESCALATE).
- **Degrade semantics**: a skipped advisory review must reuse the
  `_CODE_REVIEW_SKIP_PREFIX` loud-skip convention (`qa.py:189-204`) so
  "not reviewed" never reads as "reviewed clean".
- **Neutral-brief discipline is structural**: `TriageBrief`/review briefs have
  no field for caller reasoning — enforce with model design, not prompt hopes.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `codex` CLI (external binary) | operator-installed, authed | the sub-agent runtime; absence degrades per FEAT-250 G4 |
| — no new Python deps — | | everything builds on existing dev_loop machinery |

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — one worktree, tasks strictly sequential.
- Modules 1→2 could run in parallel in principle, but 3→4→5→6→7 form a chain
  on shared files (`models.py`, `code_review.py`, `qa.py`); a single worktree
  avoids cross-task merge pain for no real wall-clock gain.
- **Cross-feature dependencies**: none merged-pending. Coordinate `conf.py`
  additions with in-flight FEAT-374 (not yet committed) — append-only rule
  above.

---

## 8. Open Questions

### Resolved (carried from proposal + spec Q&A — do not re-open)

- [x] Replace the write-enabled codex reviewer or coexist? — *Resolved in
  proposal (U1)*: coexist; separate `"codex-adversarial"` factory entry;
  `DEV_LOOP_CODEREVIEW_AGENT` selects; no behavior change for existing users.
- [x] Who consumes CONFIRM/REJECT/ESCALATE? — *Resolved in proposal (U2)*:
  QANode feeds advisory findings into the review→fix→rerun loop; the primary
  worker triages each finding (CONFIRM: fix, REJECT: record reason,
  ESCALATE: gate).
- [x] v2 scope (exec review variants, resume, parallel perspective)? —
  *Resolved in proposal (U3)*: include everything in this feature.
- [x] Where does ESCALATE land? — *Resolved in spec Q&A*: FEAT-322 HITL gate
  (`review_escalation`, fail-closed) AND a note in `QAReport.notes` → PR body.
- [x] Parallel-perspective synthesis executor? — *Resolved in spec Q&A*:
  deterministic merge always; LLM judge added only when
  `DEV_LOOP_CODEREVIEW_JUDGE=true`.

### Unresolved (implementation-time)

- [ ] Does the installed `codex` CLI's `exec review` subcommand accept
  `--json` + `--output-schema`? Verify in Module 3; fallback path specified
  in §7. — *Owner: implementer (TASK for Module 3)*
- [ ] Diff-size cap for the neutral brief on very large changes (truncate vs.
  file-list summary)? Decide in Module 2 with a sensible default. —
  *Owner: implementer*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-26 | Jesus Lara + Claude (from FEAT-375 proposal) | Initial draft |
