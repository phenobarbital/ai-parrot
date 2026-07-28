# TASK-1970: Console kind picker, feature wizard path, pool/judge steps, flags

**Feature**: FEAT-388 — `parrot devloop` CLI Homologation
**Spec**: `sdd/specs/devloop-cli-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1968, TASK-1969
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (goals G2, G3, G5, G7). Wires the intake (TASK-1969) and
the catalog (TASK-1968) into `DevLoopConsole` and the click surface: a kind
picker routes `feature` requests to the free-text intake with no
Jira/CloudWatch questions; a dev-agent pool step and judge-panel step mirror
the web console's rows; `--dev-agent` / `--text` enable non-interactive use.

---

## Scope

- **Kind picker**: interactive `run` (no `--brief`) first asks
  `bug / enhancement / feature?`. `bug`/`enhancement` → existing WorkBrief
  wizard **byte-identical** (the chosen kind pre-fills `WorkBrief.kind`),
  plus the optional dev-agent pool step. `feature` → intake path.
- **Feature path**: multiline free-text prompt → `FeatureIntake.generate` →
  Rich panel (draft fields + generated document path) →
  `accept / edit <field> / redo <guidance> / cancel` loop → pool step →
  judge step → `_dispatch_run`.
- **Pool step** (optional, both paths): rows of `DevAgentSpec`
  (backend/model/count) via `PydanticWizard` list collection; backend
  choices + default-model hints from the catalog; default = skip (pool
  `None`).
- **Judge step** (feature path only, optional): rows of `JudgeSpec`;
  choices limited to the catalog's `JUDGE_BACKENDS`; default =
  `default_judge_panel_payload()`.
- **`/feature` slash command** → feature path (register in the handlers
  dict).
- **Click options on `run`**: repeatable
  `--dev-agent backend[:model[:count]]` (split on `:` max 2; fail fast on
  unknown backend listing catalog ids) and `--text "<request>"`
  (non-interactive intake; `--yes` skips the confirm loop). Flags merge into
  the built brief; `--brief` wins over flags for fields it sets.
- Tests for parsing, routing, and the intake loop (fake session + fake
  runner, per the existing console E2E pattern).

**NOT in scope**: bootstrap/preflight (TASK-1971); docs (TASK-1972);
any change to `_load_brief` / `parse_brief` semantics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/console.py` | MODIFY | Kind picker, feature path, steps, `/feature` |
| `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` | MODIFY | `--dev-agent`, `--text` options |
| `packages/ai-parrot/tests/cli/devloop/test_console_feature_path.py` | CREATE | Routing + loop tests |
| `packages/ai-parrot/tests/cli/devloop/test_pool_flags.py` | CREATE | Flag parsing tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-28 on `dev` @ `623f0a6`.

### Verified Imports

```python
from parrot.cli.wizard import (
    PydanticWizard,        # wizard.py:55
    WizardConfig,          # wizard.py:48
    WizardFieldOverride,   # wizard.py:40
)
from parrot.flows.dev_loop.models import (
    WorkBrief,             # models.py:138
    DevAgentSpec,          # models.py:388
    FeatureBrief,          # models.py:1068
    JudgeSpec,             # models.py:1173
    JudgePanelConfig,      # models.py:1209
)
from parrot.flows.dev_loop import catalog            # created by TASK-1968
from parrot.cli.devloop.intake import FeatureIntake  # created by TASK-1969
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/cli/devloop/console.py
class DevLoopConsole:                                          # :30
    async def _collect_work_brief(self, brief_file=None) -> Any:   # :106
    def _load_brief(self, path_str: str) -> Any:                   # :166
    def _print_feature_brief_summary(self, brief: Any) -> None:    # :215
    async def _dispatch_run(self, brief: Any) -> str:              # :239
    async def _dispatch_command(self, raw: str) -> None:           # :482
    # handlers dict at :488 — add "feature": self._cmd_feature
    async def _cmd_new(self, args: str) -> None:                   # :577

# packages/ai-parrot/src/parrot/cli/wizard.py
async def collect(self, *, initial: Optional[Dict[str, Any]] = None) -> BaseModel:  # :72
async def _collect_list(...)                                   # :271 (list-of-submodel rows)
def render_summary(self, instance: BaseModel) -> None:         # :412

# packages/ai-parrot/src/parrot/cli/devloop/__init__.py — current options
# run: --brief (click.Path, exists=True), --yes (flag). Console entry:
# DevLoopConsole().start(brief_file=...) — extend start()/run_cmd kwargs.
```

### Does NOT Exist

- ~~`/feature` command~~, ~~`--dev-agent`~~, ~~`--text`~~ — this task adds
  them (today's `run` options are only `--brief` / `--yes`).
- ~~Interactive FeatureBrief wizard~~ — the FEAT-374 docstring
  (`console.py:107-116`) declares it out of scope; this task supersedes that
  note via the intake path — update the docstring.
- ~~`catalog.ROLES`~~ — use `catalog.backends_for_role()` /
  `catalog.JUDGE_BACKENDS`.
- ~~`WorkBrief.judge_panel`~~ — judges exist only on `FeatureBrief`.

---

## Implementation Notes

### Key Constraints
- WorkBrief wizard fields, prompts, and order must remain byte-identical
  for `bug`/`enhancement` (G7) — the kind picker only pre-fills `kind` and
  appends the optional pool step at the end.
- Kind picker + gates share the modal-terminal discipline: pause/resume the
  active `RunView` around prompts (see `_handle_gates`, `console.py:382`).
- `--dev-agent` parsing: `value.split(":", 2)` → backend, model?, count?;
  count must be a positive int; validate backend via
  `catalog.get_backend()`; raise `click.BadParameter` listing
  `", ".join(b.id for b in catalog.BACKENDS)`.
- `--text` without `--yes` still runs the confirm loop; `--text --yes`
  dispatches on first accept-equivalent (G5 forbids silent dispatch only in
  the interactive path; `--yes` is the explicit opt-out).
- Errors surface via the `Brief error:` pattern (`console.py:86`).

### References in Codebase
- `packages/ai-parrot/tests/cli/test_devloop_feature_brief.py` — CLI wiring
  test pattern (click runner).
- TASK-1898 console E2E (fake flow) — fake-session pattern for the loop
  tests.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/cli/ -v` passes (new + existing).
- [ ] Feature path asks for no Jira ticket and no log sources (G3).
- [ ] `--dev-agent codex:gpt-5.5:2 --dev-agent <google-backend-id>` →
      `[DevAgentSpec(codex, "gpt-5.5", 2), DevAgentSpec(<id>)]` (G2).
- [ ] Unknown backend → `click.BadParameter` with catalog ids.
- [ ] `run --brief <file>` behavior byte-identical for both brief kinds (G7).
- [ ] Intake never dispatches without accept (or `--yes`) (G5).
- [ ] `ruff check` clean.

---

## Test Specification

```python
# test_pool_flags.py
def test_parse_backend_only(): ...
def test_parse_backend_model(): ...
def test_parse_backend_model_count(): ...
def test_unknown_backend_lists_catalog_ids(): ...
def test_count_must_be_positive_int(): ...

# test_console_feature_path.py (fake session/runner)
async def test_kind_picker_bug_reaches_workbrief_wizard(): ...
async def test_kind_picker_feature_runs_intake(): ...
async def test_feature_command_enters_intake(): ...
async def test_redo_regenerates_with_guidance(): ...
async def test_cancel_dispatches_nothing(): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1968 and TASK-1969 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/devloop-cli-homologation.json`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index**, **fill the Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-28
**Notes**: Kind picker (`bug/enhancement/feature`, defaults to `bug` on
EOF/empty) implemented as a new `_prompt_kind()`; `bug`/`enhancement`
pre-fill `WorkBrief.kind` via `initial={"kind": kind}` (skips only that
field's own prompt — every other field/prompt/order byte-identical,
verified by the still-passing pre-existing `test_devloop_feature_brief.py`
suite) and append an optional dev-agent pool step; `feature` routes to
a new `_collect_feature_brief()` (draft → Rich panel →
accept/edit/redo/cancel loop, never Jira/log-source prompts) with
optional pool + judge-panel steps after write. `/feature` registered in
the handlers dict. `--dev-agent backend[:model[:count]]` (repeatable,
colon-split max 2) and `--text` (+ `--yes`) added to `run`; flags merge
into whichever brief is built, `--brief` file wins when it already sets
`dev_agents`.

Deliberately did **not** touch `wizard.py` (not in this task's file
list, despite the spec's Implementation Notes mentioning
"or extend WizardFieldOverride minimally" as an option) — instead wrote
bespoke, catalog-filtered numbered pickers (`_prompt_backend_choice` +
`_collect_dev_agent_pool`/`_collect_judge_panel`) directly in
`console.py`. This also let me defensively handle a real, pre-existing
gap I found while verifying the Codebase Contract: `catalog.
JUDGE_BACKENDS` includes `google_coding` (which `code_review.py`'s
`_build_judge` now supports) but `JudgeSpec._agent_must_have_review_
profile`'s hardcoded validator tuple in `models.py` does **not** — so
picking `google_coding` as a judge raises `pydantic.ValidationError`.
Since `models.py` is explicitly out of scope ("zero model changes"), I
catch that `ValidationError` in `_collect_judge_panel`/
`_collect_dev_agent_pool` and let the user retry the row instead of
crashing the wizard. **Flagging this for a follow-up task**: either add
`google_coding` to that validator's `supported` tuple, or drop it from
`catalog.JUDGE_BACKENDS` until it does.

Also found and fixed a regression during implementation: `ruff check
--fix` initially rewrote type-hint style (`Optional`/`Dict`/`List` →
modern `X | None`/`dict`/`list`, plus stripped `# noqa: PLC0415`
comments and `asyncio.TimeoutError` → `TimeoutError`) across pre-existing
methods I never touched. Manually reverted all of those to their exact
original form (only `_prompt_kind`, `_collect_workbrief_wizard`,
`_collect_feature_brief`, and the other genuinely-new/rewritten methods
keep modern style) — confirmed via `git diff` that the final diff is
scoped to only the intended additions. Separately, `ruff --fix` also
briefly broke `test_console_e2e_fake_flow` (an existing integration test
patches `_collect_work_brief` with a narrow single-arg fake) by always
passing the 3 new kwargs from `_dispatch_initial`; fixed by only passing
them when at least one is non-default, keeping the old call shape
byte-identical otherwise.

`pytest packages/ai-parrot/tests/cli/ -v` → 123 passed (13 new +
110 pre-existing, zero regressions).

**Deviations from spec**: none in behavior. Implementation detail only:
catalog-filtered backend pickers are bespoke console.py helpers rather
than a `WizardFieldOverride` extension, since `wizard.py` was not in
this task's file list.
