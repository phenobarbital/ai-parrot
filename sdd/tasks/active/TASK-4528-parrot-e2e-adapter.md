# TASK-4528: parrot-e2e runner adapter reading `e2e-verdict.json`

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4521
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (parrot-e2e); brainstorm Q3: never in the task tier. FEAT-581's runner writes
`e2e-verdict.json` (`packages/ai-parrot-server/src/parrot/e2e/runner.py:46`) with `results`, `counts`, `exit_code`.
The kernel must NOT import `parrot.e2e` (Pydantic, server package) — read the JSON from disk.

---

## Scope

- Create `runners/parrot_e2e.py` (`ADAPTER = ParrotE2EAdapter()`), `default_tiers = {merge, feature}`.
- Argv: `parrot e2e run --plan <plan> --owner-id sdd-coder:<feature>` (owner id from settings `owner_id`, default `sdd-coder`).
- `parse_e2e_verdict(path, …)`: map `results[*]` to nodes (`status` passed/failed/skipped), `detail`/`message` to `failure_text`; missing file ⇒ `no_report` (red).
- `validate_settings`: `plan` required and must exist; `tiers` containing `task` ⇒ diagnostic.
- Fixture `e2e-verdict.json` modelled on `E2EVerdict` (models.py:504).

**NOT in scope**: Starting/stopping targets (the CLI does it); exploration agents.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/parrot_e2e.py` | CREATE | adapter + parser |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/e2e-verdict.json` | CREATE | fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_parrot_e2e.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
import json
from ..datatypes import Invocation, RunReport, TestTarget  # TASK-4520
from ..policy import ScopePolicy
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/e2e/runner.py:46-47  _VERDICT_NAME = "e2e-verdict.json"; _POINTER_NAME = "latest.json"
# packages/ai-parrot-server/src/parrot/e2e/models.py:504  class E2EVerdict — schema_version, feature_id, run_id, policy,
#   selected_node_ids, collected_node_ids, results, counts, argv, exit_code
# packages/ai-parrot-server/src/parrot/e2e/cli.py:392-396  `e2e run --plan <path> --owner-id <id>`
```

### Does NOT Exist
- ~~`import parrot.e2e` from the kernel~~ — forbidden (stdlib-only, server package)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/parrot_e2e.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/e2e-verdict.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_parrot_e2e.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/e2e/models.py#E2EVerdict"
  ]
}
```

---

## Implementation Notes

- Read `E2EVerdict`'s `results` item fields from models.py before writing the fixture; if a field name differs from this task's assumption (`node_id`, `status`, `detail`), follow the model and note it in the Completion Note.
- `report_path`: the adapter sets it to `<evidence dir>/e2e-verdict.json`; the supervisor resolves the evidence dir from the CLI's `latest.json` pointer when the file is not where expected (FILL IN in parse_report).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Read E2EVerdict result item model — *why*: fixture must match.
2. Adapter + parser.
3. Tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/parrot_e2e.py` (CREATE)
```python
"""parrot-e2e runner adapter: reads e2e-verdict.json, never imports parrot.e2e (FEAT-709 M4). Stdlib only."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..datatypes import Invocation, RunReport, TestTarget
from ..policy import ScopePolicy


def parse_e2e_verdict(path: Path | None, *, exit_code: int, suite: str, duration_s: float, timed_out: bool) -> RunReport:
    """e2e-verdict.json ⇒ RunReport. Missing/unreadable ⇒ "no_report" (red)."""
    # FILL IN: json.loads; results ⇒ nodes; counts ⇒ totals; detail/message ⇒ failure_text
    raise NotImplementedError


class ParrotE2EAdapter:
    kind = "parrot-e2e"
    binaries = ("parrot",)
    default_tiers = frozenset({"merge", "feature"})
    report_format = "e2e-verdict"

    def matches(self, argv: Sequence[str]) -> bool:
        return len(argv) >= 3 and Path(argv[0]).name == "parrot" and argv[1] == "e2e" and argv[2] in {"run", "verify"}

    def operands(self, argv: Sequence[str]) -> list[str] | None:
        return [] if self.matches(argv) else None

    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool:
        return False

    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]:
        return []

    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str:
        return Path(settings["plan"]).parent.name or "e2e"

    def invocation(self, targets: Sequence[TestTarget], *, distribution: str, worktree: Path,
                   settings: Mapping[str, str], policy: ScopePolicy, report_path: str) -> Invocation:
        owner = settings.get("owner_id", "sdd-coder")
        argv = ("parrot", "e2e", "run", "--plan", settings["plan"], "--owner-id", owner)
        return Invocation(distribution=distribution, argv=argv, targets=tuple(targets), runner=self.kind,
                          report_path=report_path, report_format=self.report_format)

    def parse_report(self, *, report_path: Path | None, exit_code: int, stdout: str, stderr: str,
                     duration_s: float, timed_out: bool, suite: str) -> RunReport:
        # FILL IN: when report_path missing, resolve via the latest.json pointer beside it; then parse_e2e_verdict
        raise NotImplementedError

    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]:
        # FILL IN: plan required + exists; "task" in settings.get("tiers","") ⇒ "parrot-e2e: task tier forbidden"
        return []


ADAPTER = ParrotE2EAdapter()
```
**Why**: Tier restriction is enforced twice by design: here (diagnostic) and in contract validation (TASK-4522).

### FILL IN checklist
- [ ] `parse_e2e_verdict`
- [ ] `parse_report` pointer fallback
- [ ] `validate_settings`
- [ ] fixture
- [ ] tests

---

## Acceptance Criteria

- [ ] Fixture parses to the right counts and failing node text.
- [ ] Missing file ⇒ `no_report` and a red status.
- [ ] `default_tiers` excludes `task`; `validate_settings` flags a `task` tier.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_parrot_e2e.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4528 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
