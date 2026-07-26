# TASK-1902: `codex-adversarial` + `parallel` review dispatchers

**Feature**: FEAT-375 — Codex CLI Adversarial Second-Opinion Agent
**Spec**: `sdd/specs/codex-cli-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1899, TASK-1900, TASK-1901
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-375 (spec §3, goals G1+G7). Registers the advisory reviewer
and the composite parallel-perspective reviewer in the FEAT-270 factory,
coexisting with the write-enabled `claude-code`/`codex`/`gemini` entries.

---

## Scope

- MODIFY `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`:
  - Add class attribute `advisory: bool = False` on `AbstractCodeReviewDispatcher`.
  - `@CodeReviewDispatcherFactory.register("codex-adversarial")`
    `class CodexAdversarialReviewDispatcher(AbstractCodeReviewDispatcher)`:
    `agent_name="codex-adversarial"`, `advisory=True`;
    `__init__(*, dispatcher: CodexCodeDispatcher, model: str | None = None,
    review_scope: str = "uncommitted", review_base: str = "", review_commit: str = "")`;
    `build_review_profile()` → `CodexAdversarialReviewProfile`. Model default:
    `conf.DEV_LOOP_ADVERSARIAL_MODEL` if present else `"gpt-5.5"` (conf key
    lands in TASK-1904 — use `getattr(conf, "DEV_LOOP_ADVERSARIAL_MODEL", "gpt-5.5")`).
    Post-dispatch hardening: force `verdict.files_modified = []` (advisory
    NEVER modifies files) and tag findings' `source`.
  - `@CodeReviewDispatcherFactory.register("parallel")`
    `class ParallelPerspectiveReviewDispatcher(AbstractCodeReviewDispatcher)`:
    `agent_name="parallel"`, `advisory=True`;
    `__init__(*, primary: AbstractCodeReviewDispatcher,
    adversary: AbstractCodeReviewDispatcher, judge_dispatcher: Any | None = None,
    judge_enabled: bool = False)`.
    Overrides `review()`: `asyncio.gather(primary.review(...), adversary.review(...))`
    with per-side degrade (one side failing → other side's verdict + nit
    finding, FEAT-250 G4); then **deterministic merge**:
    - agreement key: `(finding.file, normalize(finding.message))` where
      `normalize` = casefold + collapse whitespace;
    - agreements tagged with both sources; disagreements keep single source;
    - merged `CodeReviewVerdict.passed = primary.passed and adversary.passed`;
    - `files_modified` = primary's only (adversary is read-only).
    - Optional judge: only when `judge_enabled` and `judge_dispatcher` is not
      None — one extra dispatch producing `PerspectiveSynthesis.judge_summary`
      appended to `verdict.summary`. Judge failure degrades silently to the
      deterministic merge (log warning).
  - Export both in `__all__` (code_review.py:191-197).
- Unit tests (see Test Specification).

**NOT in scope**: QANode consumption of `advisory` (TASK-1903); conf.py keys
(TASK-1904); command shapes (TASK-1901, already landed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | MODIFY | 2 new dispatchers + `advisory` attr + merge helper |
| `packages/ai-parrot/tests/flows/dev_loop/test_adversarial_review.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-26 on `dev` @ `ec6e0432a`.

### Verified Imports
```python
from parrot.flows.dev_loop.code_review import (          # __all__: code_review.py:191-197
    AbstractCodeReviewDispatcher,                        # code_review.py:35
    CodeReviewDispatcherFactory,                         # code_review.py:104
)
from parrot.flows.dev_loop.dispatcher import CodexCodeDispatcher  # dispatcher.py:936
from parrot.flows.dev_loop.models import (
    CodeReviewFinding,   # models.py:739
    CodeReviewVerdict,   # models.py:748  (passed, findings, summary, files_modified)
)
from parrot.flows.dev_loop.models import (  # from TASK-1899 — verify landed
    AdversarialFinding, CodexAdversarialReviewProfile, PerspectiveSynthesis,
)
from parrot import conf                                  # pattern: code_review.py:19
```

### Existing Signatures to Use
```python
# code_review.py:35-101 — the ABC (review() is the degrade wrapper)
class AbstractCodeReviewDispatcher(ABC):
    agent_name: str                                       # 49
    async def review(self, *, brief: BaseModel, run_id: str, node_id: str,
                     cwd: str, session_host: Optional[SessionHost] = None
                     ) -> CodeReviewVerdict:              # 51-84
        # delegates: self._dispatcher.dispatch(brief=brief,
        #     profile=self.build_review_profile(),
        #     output_model=CodeReviewVerdict, run_id=..., node_id=..., cwd=...,
        #     session_host=...)                            # 76-84
        # on ANY exception → passed=True + nit "code-review could not run: …"  # 85-97
    @abstractmethod
    def build_review_profile(self) -> BaseModel           # 99-101

# code_review.py:104-127 — the factory
class CodeReviewDispatcherFactory:
    @classmethod register(cls, name: str)                 # 109-117 decorator
    @classmethod create(cls, name: str, **kwargs)         # 119-127, raises ValueError on unknown

# code_review.py:151-168 — sibling to mirror (init/logger/profile pattern)
@CodeReviewDispatcherFactory.register("codex")
class CodexCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    def __init__(self, *, dispatcher: CodexCodeDispatcher, model: str | None = None):
        self._dispatcher = dispatcher; self._model = model or "gpt-5.5"
        self.logger = logging.getLogger(__name__)
```

### Does NOT Exist
- ~~registry entries `"codex-adversarial"` / `"parallel"`~~ — this task creates them (registry today: claude-code, codex, gemini).
- ~~`advisory` attribute anywhere~~ — this task adds it to the ABC.
- ~~`conf.DEV_LOOP_ADVERSARIAL_MODEL` / `DEV_LOOP_CODEREVIEW_JUDGE`~~ — land in TASK-1904; use `getattr` fallbacks until then.
- ~~a triage callback on the ABC~~ — triage lives in QANode (TASK-1903), NOT here.
- ~~`CodeReviewVerdict.sources` field~~ — source tagging lives on `AdversarialFinding.source`; merged verdict findings should be `AdversarialFinding` instances (valid: subclass of `CodeReviewFinding`).

---

## Implementation Notes

### Pattern to Follow
Mirror `CodexCodeReviewDispatcher` (code_review.py:151-168) for the advisory
class. For `ParallelPerspectiveReviewDispatcher.review()`, note it overrides
the ABC's `review()` entirely (it composes two reviewers rather than one
dispatcher) — keep the same outer degrade contract.

### Key Constraints
- Advisory verdict: `files_modified` forced to `[]` even if the model returns paths.
- Deterministic merge is pure Python — unit-testable without any dispatch.
- Never mutate the input verdicts; build a new merged `CodeReviewVerdict`.
- `asyncio.gather(..., return_exceptions=True)` for per-side degrade.

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` — factory + degrade test patterns

---

## Acceptance Criteria

- [ ] `CodeReviewDispatcherFactory.create("codex-adversarial", dispatcher=...)` works; `advisory is True`
- [ ] `create("codex", ...)` untouched — existing FEAT-270 tests green unmodified
- [ ] Advisory verdict never carries `files_modified` (test with a lying stub)
- [ ] Parallel merge: agreement detection by file+normalized message; both-source tagging
- [ ] Judge dispatch only when `judge_enabled=True` and judge present; judge failure degrades
- [ ] One-side failure → other verdict + nit finding (no exception escapes)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_adversarial_review.py -v` passes; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_adversarial_review.py
import pytest
from parrot.flows.dev_loop.code_review import (
    CodeReviewDispatcherFactory, ParallelPerspectiveReviewDispatcher,
)
from parrot.flows.dev_loop.models import CodeReviewFinding, CodeReviewVerdict

class _StubReviewer:
    advisory = False
    def __init__(self, verdict): self._v = verdict
    async def review(self, **kw): return self._v

def test_adversarial_registered():
    assert "codex-adversarial" in CodeReviewDispatcherFactory._registry
    assert CodeReviewDispatcherFactory._registry["codex-adversarial"].advisory is True

def test_parallel_registered():
    assert "parallel" in CodeReviewDispatcherFactory._registry

async def test_parallel_merge_agreement():
    f = lambda m: CodeReviewFinding(message=m, severity="major", file="a.py")
    primary = _StubReviewer(CodeReviewVerdict(passed=False, findings=[f("Off by one")]))
    adversary = _StubReviewer(CodeReviewVerdict(passed=False, findings=[f("off  by one")]))
    d = ParallelPerspectiveReviewDispatcher(primary=primary, adversary=adversary)
    v = await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert len(v.findings) == 1          # merged as agreement
    assert v.passed is False

async def test_parallel_one_side_fails():
    class _Boom:
        advisory = False
        async def review(self, **kw): raise RuntimeError("down")
    ok = _StubReviewer(CodeReviewVerdict(passed=True))
    d = ParallelPerspectiveReviewDispatcher(primary=ok, adversary=_Boom())
    v = await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert v.passed is True and any("could not run" in fi.message for fi in v.findings)

async def test_judge_not_called_when_disabled():
    called = []
    class _Judge:
        async def dispatch(self, **kw): called.append(1)
    ok = _StubReviewer(CodeReviewVerdict(passed=True))
    d = ParallelPerspectiveReviewDispatcher(primary=ok, adversary=ok,
                                            judge_dispatcher=_Judge(), judge_enabled=False)
    await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert not called
```

---

## Agent Instructions

1. **Read the spec** (§2 New Public Interfaces, §3 Module 4)
2. **Check dependencies** — TASK-1899/1900/1901 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/codex-cli-agent.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

Implemented exactly as specified, with two documented design decisions
where the task left the exact mechanism open:

- `advisory: bool = False` added to `AbstractCodeReviewDispatcher`;
  `CodexAdversarialReviewDispatcher` ("codex-adversarial") and
  `ParallelPerspectiveReviewDispatcher` ("parallel") both set
  `advisory = True`. `"codex"` (and `"claude-code"`/`"gemini"`) untouched
  and covered by a regression test (`test_codex_untouched`).
- `CodexAdversarialReviewDispatcher.review()` calls `super().review()`
  (reusing the ABC's degrade-on-infra-error wrapper) then hardens the
  result: `files_modified` forced to `[]` unconditionally, and every
  finding is re-wrapped as an `AdversarialFinding(source="codex-adversarial")`
  via `finding.model_dump()` + `model_copy(update=...)` (which does not
  revalidate, so the subclass instances survive in the
  `List[CodeReviewFinding]`-typed field). Model default:
  `getattr(conf, "DEV_LOOP_ADVERSARIAL_MODEL", "gpt-5.5")` per the task's
  explicit instruction (conf key lands in TASK-1904).
- `ParallelPerspectiveReviewDispatcher.review()` fully overrides the ABC
  (per Implementation Notes): `asyncio.gather(primary.review(...),
  adversary.review(...), return_exceptions=True)`, per-side degrade via
  `_resolve_side` (an exception on either side becomes a passing verdict
  + a "code-review could not run: …" nit finding — mirrors the ABC's own
  degrade wording so downstream consumers see one consistent phrase).
  **Design decision #1**: since sides can be duck-typed reviewers without
  an `agent_name` attribute (as in the given Test Specification's
  `_StubReviewer`), source tagging uses fixed labels `"primary"` /
  `"codex-adversarial"` rather than `self._primary.agent_name` — avoids an
  `AttributeError` on non-`AbstractCodeReviewDispatcher` duck-typed
  reviewers, at the cost of not reflecting a *different* adversary's
  actual `agent_name` if one were ever substituted. Flagging this in case
  a future task wants per-instance labels instead.
- Deterministic merge (`_merge_verdicts`): agreement key
  `(finding.file, casefold+whitespace-collapsed message)`; agreements get
  `source="primary,codex-adversarial"` (comma-joined), disagreements keep
  their single-source tag; `passed = primary.passed and adversary.passed`;
  `files_modified` = primary's only. Pure Python, no I/O, matches
  "unit-testable without any dispatch."
- **Design decision #2 (judge dispatch, spec §2 G7)**: the judge
  dispatcher's type is `Optional[Any]` by spec — no concrete interface is
  given beyond the test's `_Judge.dispatch(**kw)` stub. Implemented
  `_run_judge()` calling `judge_dispatcher.dispatch(brief=..., primary_verdict=...,
  adversary_verdict=..., run_id=..., node_id=..., cwd=..., session_host=...)`,
  accepting either a plain `str` return or an object exposing
  `.judge_summary` (e.g. a future `PerspectiveSynthesis`-shaped result).
  This is a best-effort, defensively-coded contract since the task does
  not pin down the judge's exact signature; any failure (wrong signature,
  exception) degrades silently to the deterministic merge per spec
  ("judge failure degrades silently to the deterministic merge, log
  warning") — verified by `test_judge_failure_degrades_silently`. If a
  concrete judge-dispatcher type is introduced later (TASK-1904/conf
  wiring or beyond), this call site may need to be adjusted to match its
  real signature.
- `test_adversarial_review.py`: 13 tests — the 6 from the Test
  Specification (registration ×2, merge agreement, one-side-fail, judge
  disabled) plus 7 extra covering acceptance criteria not in the minimal
  scaffold: disagreement single-source tagging, `files_modified` = primary
  only, judge-enabled summary append, judge-failure degrade, advisory
  never-carries-files_modified (lying stub), advisory finding source
  tagging, and adversarial profile defaults.

Verification: `pytest packages/ai-parrot/tests/flows/dev_loop/ -q` →
638 passed, 1 pre-existing failure (`test_models_module_is_pure`, same
known ordering-pollution issue noted in TASK-1899/1900/1901), 5 skipped.
`ruff check` clean on both touched files.

No divergence from the task spec; no files touched outside the declared
list.
