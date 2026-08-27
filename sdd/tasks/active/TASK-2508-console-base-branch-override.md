# TASK-2508: Console flow-type / base-branch override

**Feature**: FEAT-466 — Dev-Loop Run Fidelity
**Spec**: `sdd/specs/dev-loop-run-fidelity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2504
**Assigned-to**: unassigned

---

## Context

Implements **spec Module 6**.

Spec §8 resolved that `kind="bug"` should *default* to `hotfix`/`main` but the
operator must be able to override it per run. The motivating example is the
incident itself: PR #1250 was a SHA-1 → SHA-256 hardening fix. It was
classified `bug`, which under the new mapping makes it a hotfix onto `main` —
but a hardening change with no production incident behind it arguably belongs
on `dev` like any other improvement. Forcing every `bug` onto `main` would
trade one wrong default for another.

So the console needs an explicit control, and the brief needs two fields to
carry it. TASK-2502 already built `resolve_flow()` with **field-wise**
precedence precisely for this: an operator can override only the base branch
and keep the kind-derived type, or override only the type, or both.

This task is the last consumer-facing piece. It touches only the two example
servers and the two HTML consoles, plus two new optional fields on `WorkBrief`.

---

## Scope

### A. `WorkBrief` — two optional fields

Add alongside the existing per-run override fields (`dev_agents:200`,
`dev_isolation:210`), following their exact style — `Optional`, defaulting to
`None`, with a description saying that `None` means "let the flow decide":

```python
    flow_type: Optional[Literal["feature", "hotfix"]] = Field(
        default=None,
        description=(
            "FEAT-466 per-run override of the SDD flow type. None ⇒ derive "
            "from `kind` (bug ⇒ hotfix, otherwise feature)."
        ),
    )
    base_branch: Optional[str] = Field(
        default=None,
        description=(
            "FEAT-466 per-run override of the base branch. None ⇒ derive from "
            "`flow_type`/`kind` (hotfix ⇒ main, feature ⇒ dev)."
        ),
    )
```

### B. Thread them into the resolution

- `ResearchNode` (TASK-2504's `_resolve_base_branch`) must pass the brief's
  overrides into `resolve_flow(...)` as `type_override` / `base_branch_override`.
  **Coordinate with TASK-2504's implementation** — if it already threads them,
  verify; if not, add it there.
- `sdd-research`'s dispatch brief already serialises the whole `WorkBrief` as
  JSON (`dispatchers/claude.py:538` — `brief.model_dump_json()`), so the new
  fields reach the subagent automatically and TASK-2507's `--type` /
  `--base-branch` flags can be derived from them. No dispatcher change needed;
  **verify this rather than assuming it.**

### C. `examples/dev_loop/server.py`

- In the bug-brief form parser (the `payload` builder around `:930-944`), read
  `flow_type` and `base_branch` from the form and add them to `payload` only
  when present and valid — mirroring exactly how `dev_isolation` is validated
  against a set before being added (`:941-943`).
- Validate `flow_type` against `{"feature", "hotfix"}` and reject anything else
  silently (omit the key) rather than passing junk to pydantic.
- Do the same in the feature-mode payload builder around `:1142-1144`.

### D. `examples/dev_loop/server_dev.py`

- Same treatment in its payload builder (it delegates to
  `ops_server._parse_dev_agents` at `:175-177`; follow that pattern and reuse
  the ops-server helper if you add one).

### E. `examples/dev_loop/static/index.html` and `static/dev.html`

- Add a control to the same tab that already hosts the run's flow settings.
  A **base-branch select** (`auto` / `dev` / `main` / `staging`) plus a
  **flow-type select** (`auto` / `feature` / `hotfix`), both defaulting to
  `auto` (meaning: send nothing, let the flow decide).
- Add `flowType: "auto", baseBranch: "auto"` to the `app.form` initial state
  (beside `devAgents: [], devIsolation: "shared"` — `index.html:418`,
  `dev.html:441`).
- Add to the payload builders only when not `auto`:
  ```js
  if (f.flowType !== "auto") payload.flow_type = f.flowType;
  if (f.baseBranch !== "auto") payload.base_branch = f.baseBranch;
  ```
  Sites: `index.html:1344` (feature mode) and `index.html:1361-1364`
  (bug mode); the equivalents in `dev.html:1512`.
- Surface the effective values in the "ready" summary rows that already show
  `dev agents` (`index.html:724,734`; `dev.html:753,764`), so the operator can
  see what the run will do before starting it. Show the resolved default when
  `auto` (e.g. `bug → hotfix/main`), not the literal string `auto`.

### F. Guard against the invalid combination in the UI

`resolve_flow()` raises `ValueError` for `type=hotfix, base_branch != main`.
Do not let the operator submit that: when `flowType === "hotfix"`, restrict the
base-branch select to `main` (or show an inline validation message and block
submit). A server-side 400 is the backstop, not the primary UX.

**NOT in scope**:
- `resolve_flow()` itself (TASK-2502) or `ResearchOutput.base_branch`
  (TASK-2504).
- The `/sdd-spec` flags that consume these values (TASK-2507).
- The handoff guard (TASK-2505).
- Any change to `_parse_dev_agents` or the dev-agent pool UI.
- Persisting the operator's choice across runs (no localStorage work).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | `WorkBrief.flow_type` + `.base_branch` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | MODIFY | Pass overrides into `resolve_flow` (coordinate with TASK-2504) |
| `examples/dev_loop/server.py` | MODIFY | Parse + validate both fields, bug and feature payloads |
| `examples/dev_loop/server_dev.py` | MODIFY | Same |
| `examples/dev_loop/static/index.html` | MODIFY | Controls, form state, payload, summary rows |
| `examples/dev_loop/static/dev.html` | MODIFY | Same |
| `packages/ai-parrot/tests/flows/dev_loop/test_flow_type_override.py` | CREATE | Model + resolution tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from parrot.flows.dev_loop.models.base import WorkBrief, BugBrief, DevAgentSpec
from scripts.sdd.sdd_meta import resolve_flow    # TASK-2502
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
WorkKind = Literal["bug", "enhancement", "new_feature"]              # line 116

class WorkBrief(BaseModel):                                          # line 138
    """Field declaration order is intentional: `kind` is first so the JSON
    ... (see the class docstring at :146)"""
    kind: WorkKind = Field(default="bug", ...)                       # line 151
    summary: str = Field(..., min_length=10)                         # line 161
    dev_agents: Optional[List["DevAgentSpec"]] = Field(...)          # line 200  ← STYLE MODEL
    dev_isolation: Optional[Literal["shared", "isolated"]] = Field(...)  # line 210  ← STYLE MODEL

BugBrief = WorkBrief                                                 # line 223
```

```python
# examples/dev_loop/server.py — the bug payload builder
    existing = (form.get("existing_issue_key") or "").strip()
    if existing:
        payload["existing_issue_key"] = existing
    # FEAT-323: per-run dev-agent pool override.
    dev_agents = _parse_dev_agents(form.get("dev_agents"))           # line 938
    if dev_agents:
        payload["dev_agents"] = dev_agents
        isolation = (form.get("dev_isolation") or "").strip().lower()
        if isolation in {"shared", "isolated"}:                      # line 942  ← VALIDATION PATTERN
            payload["dev_isolation"] = isolation
    return payload
# feature payload builder
    dev_agents = _parse_dev_agents(form.get("dev_agents"))           # line 1142
    if dev_agents:
        payload["dev_agents"] = dev_agents                           # line 1144
def _parse_dev_agents(raw: Any) -> Optional[list[DevAgentSpec]]:     # line 1012
```

```python
# examples/dev_loop/server_dev.py
    dev_agents = ops_server._parse_dev_agents(form.get("dev_agents"))  # line 175
    if dev_agents:
        payload["dev_agents"] = dev_agents                             # line 177
```

```javascript
// examples/dev_loop/static/index.html
    devAgents: [], devIsolation: "shared",                           // line 418  ← STATE
        ["dev agents", f.devAgents.length ? ... : "planner-sized"],   // line 724  ← SUMMARY ROW
        ["dev agents", f.devAgents.length ? ... : "server default"],  // line 734  ← SUMMARY ROW
    { id: "agents", label: "Agents & models" },                      // line 1092 ← TAB
    if (f.devAgents.length) payload.dev_agents = f.devAgents;         // line 1344 ← FEATURE PAYLOAD
    if (f.devAgents.length) {                                         // line 1361 ← BUG PAYLOAD
      payload.dev_agents = f.devAgents;
      payload.dev_isolation = f.devIsolation;
    }

// examples/dev_loop/static/dev.html
    devAgents: [], devIsolation: "shared",                           // line 441
        ["dev agents", ...],                                          // lines 753, 764
    { id: "agents", label: "Agents & models" },                      // line 1292
    if (f.devAgents.length) payload.dev_agents = f.devAgents;         // line 1512
```

```python
# The brief reaches the subagent as full JSON — no dispatcher change needed
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py
        brief_json = brief.model_dump_json()                          # line 538
```

### Does NOT Exist

- ~~`WorkBrief.flow_type`~~ / ~~`WorkBrief.base_branch`~~ — verified absent;
  the brief carries `kind`, `dev_agents`, `dev_isolation` and no flow metadata.
- ~~`WorkBrief.type`~~ — do not name it `type`; that shadows the builtin and
  diverges from `FlowMeta.type` only by accident. Use `flow_type`.
- ~~a shared JS module between `index.html` and `dev.html`~~ — they are two
  standalone single-file consoles with duplicated logic. You must edit **both**;
  do not attempt to factor them into a shared file as part of this task.
- ~~`static/afd.html` needing the change~~ — verify its role before touching it;
  it is a third console and may be out of scope. State your finding in the
  Completion Note.
- ~~a form-validation framework in the consoles~~ — validation is inline
  vanilla JS. Follow the surrounding style.

---

## Implementation Notes

### Pattern to Follow — server-side parsing

Copy the `dev_isolation` idiom verbatim: read, normalise, validate against a
literal set, add only on success.

```python
    flow_type = (form.get("flow_type") or "").strip().lower()
    if flow_type in {"feature", "hotfix"}:
        payload["flow_type"] = flow_type

    base_branch = (form.get("base_branch") or "").strip()
    if base_branch:
        payload["base_branch"] = base_branch
```

Note the asymmetry and keep it: `flow_type` is a closed set and must be
validated; `base_branch` is deliberately open (CLAUDE.md allows sub-feature
branches as a base), so accept any non-empty string and let
`resolve_flow`/`FlowMeta` reject an invalid *combination*.

### Pattern to Follow — the resolution hand-off

```python
        # nodes/research.py, inside _resolve_base_branch (TASK-2504)
        meta = resolve_flow(
            doc_path=spec_path,
            kind=getattr(brief, "kind", None),
            type_override=getattr(brief, "flow_type", None),
            base_branch_override=getattr(brief, "base_branch", None),
        )
```

Use `getattr` with a default so this stays safe if a caller passes an older
brief shape.

### Key Constraints

- **`None` must mean "no opinion"**, never `""`. An empty-string
  `base_branch` reaching `resolve_flow` as an override would win over the kind
  mapping and resolve to `dev` — a silent wrong default. Filter empties at the
  server boundary (the pattern above does).
- **`auto` never reaches Python.** The consoles omit the key entirely; do not
  add `"auto"` handling to the models.
- Both consoles must stay in sync. After editing, diff the two payload builders
  to confirm the same fields are sent.
- Keep the summary rows honest: showing `auto` teaches the operator nothing.
  Show the resolved outcome (`bug → hotfix / main`), computed in JS from the
  same mapping.
- The invalid `hotfix` + non-`main` combination must be unreachable from the UI,
  and must still 400 cleanly if posted directly.

### References in Codebase

- `models/base.py:200-221` — `dev_agents` / `dev_isolation`, the exact field
  style to copy.
- `server.py:938-944` — the validation idiom to copy.
- `index.html:1361-1364` — the bug payload block your lines sit beside.
- `spec §8` — the resolved question explaining *why* this override exists
  (the #1250-was-not-really-a-hotfix argument).

---

## Acceptance Criteria

- [ ] `WorkBrief.flow_type` and `.base_branch` exist, both `Optional`,
      defaulting to `None`
- [ ] An existing brief with neither field still validates (regression guard)
- [ ] `flow_type` accepts only `feature` / `hotfix`; anything else is a
      validation error at the model and is omitted at the server boundary
- [ ] `ResearchNode` passes both into `resolve_flow` as
      `type_override` / `base_branch_override`
- [ ] `base_branch="dev"` on a `kind="bug"` run resolves to `feature`/`dev`
      and the PR targets `dev` — the operator override reaches the PR
- [ ] `base_branch=""` or absent is treated as "no opinion", not as `dev`
- [ ] `flow_type="hotfix"` with `base_branch="dev"` is rejected (400 from the
      server, `ValueError` from `resolve_flow`) and is unreachable in the UI
- [ ] Both `server.py` payload builders (bug at ~:938, feature at ~:1142) and
      `server_dev.py` parse the fields
- [ ] Both consoles expose the controls, default to `auto`, omit the keys when
      `auto`, and show the *resolved* values in the ready summary
- [ ] Confirmed (and noted) whether `static/afd.html` needs the change
- [ ] The brief still serialises to the subagent with the new fields present
      (assert on `brief.model_dump_json()`)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` and `mypy` clean on all changed Python files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_flow_type_override.py
import json

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.models.base import WorkBrief


def _brief(**over) -> WorkBrief:
    base = dict(kind="bug", summary="something broke badly", affected_component="x")
    base.update(over)
    return WorkBrief(**base)


class TestBriefFields:
    def test_defaults_are_none(self):
        b = _brief()
        assert b.flow_type is None and b.base_branch is None

    def test_legacy_brief_still_validates(self):
        """Regression guard — every existing caller omits both fields."""
        assert _brief().kind == "bug"

    def test_flow_type_is_a_closed_set(self):
        with pytest.raises(ValidationError):
            _brief(flow_type="hotfixx")

    def test_base_branch_is_open(self):
        """Sub-feature branches are legal bases (CLAUDE.md)."""
        assert _brief(base_branch="feat/parent").base_branch == "feat/parent"

    def test_fields_survive_json_round_trip(self):
        """The dispatcher sends brief.model_dump_json() to the subagent."""
        data = json.loads(_brief(flow_type="feature", base_branch="dev").model_dump_json())
        assert data["flow_type"] == "feature"
        assert data["base_branch"] == "dev"


class TestOverrideReachesResolution:
    async def test_bug_with_dev_override_resolves_to_feature_dev(self, tmp_path):
        """Reuse the ResearchNode fixtures from test_research_base_branch.py
        (TASK-2504)."""
        ...

    async def test_empty_base_branch_is_not_an_override(self, tmp_path):
        ...

    async def test_hotfix_off_main_is_rejected(self, tmp_path):
        ...


class TestServerPayloadParsing:
    """Import the payload builders from examples/dev_loop/server.py and feed
    them dicts — see how the existing server tests import it, if any."""

    def test_invalid_flow_type_is_omitted(self):
        ...

    def test_auto_never_reaches_the_payload(self):
        ...
```

---

## Agent Instructions

1. **Check your dependency**: TASK-2504 completed. Read its Completion Note —
   it records the `scripts.sdd` import decision and whether it already threads
   the brief overrides into `resolve_flow`. Do not duplicate that work.
2. **Read the spec** — §3 Module 6, and §8's resolved question on operator
   choice (it contains the reasoning you should preserve in the UI copy).
3. **Verify the Codebase Contract** — the HTML line numbers drift with every
   console edit. Re-grep before touching:
   ```bash
   grep -n "devAgents\|devIsolation" examples/dev_loop/static/index.html \
        examples/dev_loop/static/dev.html
   ```
4. **Do the Python side first, then the consoles.** The models and servers are
   testable; the HTML is not, so land the verified half before the manual half.
5. **Exercise the consoles by hand.** Start the server, submit a run with each
   combination (`auto`, explicit `dev` on a bug, explicit `hotfix`), and confirm
   the payload on the wire. Paste what you observed into the Completion Note —
   there are no automated tests for the HTML.
6. Move this file to `sdd/tasks/completed/` and set the index entry to `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**afd.html finding**:

**Observed payloads (manual console run)**:

**Deviations from spec**: none | describe if any
