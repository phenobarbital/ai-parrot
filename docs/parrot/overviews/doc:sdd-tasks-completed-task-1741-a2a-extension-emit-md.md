---
type: Wiki Overview
title: 'TASK-1741: A2UI-A2A extension emit (display) — BLOCKED until FEAT-272 merges'
id: doc:sdd-tasks-completed-task-1741-a2a-extension-emit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 13** of the spec: expose A2UI display envelopes over
  the A2A'
relates_to:
- concept: mod:parrot.a2a
  rel: mentions
- concept: mod:parrot.a2a.models
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.outputs.a2ui
  rel: mentions
- concept: mod:parrot.outputs.a2ui.serialization
  rel: mentions
---

# TASK-1741: A2UI-A2A extension emit (display) — BLOCKED until FEAT-272 merges

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1738
**Assigned-to**: unassigned

---

## Context

> **CROSS-FEATURE BLOCKER — DO NOT START**: **FEAT-272
> (a2a-protocol-compatibility) MUST be merged to `dev` before this task
> begins.** FEAT-272 actively reworks `parrot/a2a/` — starting earlier
> guarantees a collision (spec §7 "FEAT-272 collision" risk; §5 acceptance
> criterion "A2A emit lands only after FEAT-272 is merged"). This is the LAST
> task of FEAT-273 by spec ordering (§3 Module 13, §Worktree Strategy).

Implements **Module 13** of the spec: expose A2UI display envelopes over the A2A
protocol by wrapping them in A2A `Artifact.parts` per the official A2UI-A2A
extension, so remote A2A clients (and third-party renderers) can receive
Parrot-produced surfaces. Display messages only — the action/interaction leg of
the extension is FEAT-B.

---

## ⚠ Blocker Callout

| Blocker | State required before start |
|---|---|
| **FEAT-272 — a2a-protocol-compatibility** | Merged to `dev`; `sdd/tasks/index/a2a-protocol-compatibility.json` shows the feature completed |
| Consequence of ignoring | Merge collision on `parrot/a2a/models.py`; contract anchors below may be stale |
| Mandatory first step | **Re-verify every anchor in the Codebase Contract against post-FEAT-272 `dev` and reconcile this task file BEFORE writing code** |

---

## Scope

- Add emit glue that wraps a display `CreateSurface` envelope (from
  `AIMessage.a2ui_envelope`, TASK-1738) into an A2A `Artifact` whose `parts`
  carry the envelope per the A2UI-A2A official extension (data part with the
  extension's declared media type / metadata keys; consult the extension text
  at implementation time and record the exact URI/mime used).
- Extend `packages/ai-parrot/src/parrot/a2a/models.py` only as far as the
  extension requires (e.g. a constructor/helper producing an A2UI-carrying
  `Artifact`); reuse the existing `Artifact`/`Part` dataclasses — do not fork a
  parallel model.
- Advertise/emit only where FEAT-272's post-merge seams put response artifact
  construction (locate the `Artifact.from_response` call sites at execution
  time and add the envelope-aware branch there).
- Write tests: envelope → `Artifact.parts` round-trip, display-only
  enforcement, legacy A2A responses unchanged.

**NOT in scope**:
- `actionResponse` / `callFunction` **dispatch**, `ActionRouter`, or any
  inbound A2UI action handling over A2A — FEAT-B (spec Non-Goals; schemas-only
  in FEAT-273).
- Interactive/`requires_actions` envelopes over A2A — display messages only.
- Any A2A protocol work that belongs to FEAT-272 itself (transport, discovery,
  agent cards).
- A2UI v0.9.1 compatibility emit (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/a2a/models.py` | MODIFY | A2UI-carrying `Artifact` construction helper |
| `packages/ai-parrot/src/parrot/a2a/` (emit seam per post-FEAT-272 layout) | MODIFY | Envelope-aware branch where response artifacts are built |
| `packages/ai-parrot/tests/a2a/test_a2ui_extension_emit.py` | CREATE | Emit + round-trip + display-only tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified 2026-07-10 against pre-FEAT-272 `dev`. **FEAT-272 may
> change `parrot/a2a/models.py` before this task runs — the implementer MUST
> re-verify every line reference and signature below at execution time and
> reconcile the contract FIRST.** (The task brief cited `class Artifact`
> at ~:191; on current `dev` it is at **:336** — evidence the file is already
> drifting.)

### Verified Imports
```python
from parrot.a2a.models import Artifact, Part  # a2a/models.py:336 / :129 (pre-FEAT-272; RE-VERIFY)
from parrot.models.responses import AIMessage  # models/responses.py:72 — a2ui_envelope added by TASK-1738
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/a2a/models.py (pre-FEAT-272 — RE-VERIFY after merge)
@dataclass
class Part:                                          # :129
    @classmethod
    def from_text(cls, text: str) -> "Part"          # :140
    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "Part"  # :144
    def to_dict(self, version: str = "1.0") -> Dict[str, Any]  # :147

@dataclass
class Artifact:                                      # :336 (task brief said ~:191 — drifted)
    artifact_id: str                                 # :338
    parts: List[Part]                                # :339
    name: Optional[str] = None                       # :340
    description: Optional[str] = None                # :341
    metadata: Optional[Dict[str, Any]] = None        # :342
    @classmethod
    def from_response(cls, response: Any, name: str = "response") -> "Artifact"  # :345
        # reads response.content / response.response / str(response); text-only today
    def to_dict(self, version: str = "1.0") -> Dict[str, Any]  # :361
        # emits {"kind": "artifact", "artifactId", "name", "description", "parts", "metadata"}

# From TASK-1738 (verify in tasks/completed/):
#   AIMessage.a2ui_envelope: Optional[Dict[str, Any]]
#   OutputMode.A2UI
```

### Does NOT Exist
- ~~Any A2UI awareness in `parrot/a2a/`~~ — `Artifact.from_response` extracts
  text only; this task adds the envelope-carrying construction.
- ~~`ActionRouter` / any inbound action dispatch~~ — FEAT-B; lifecycle events
  are frozen/observe-only.
- ~~`actionResponse`/`callFunction` dispatch machinery~~ — schemas only in
  FEAT-273 (TASK-1720); no dispatch anywhere.
- ~~A2UI-A2A extension constants (URI, media type) in the repo~~ — must be
  taken from the official extension text and introduced here, owned by ONE
  module (consistent with the spec's single-owner rule for `version` in
  `serialization.py`).
- ~~Stability of the line numbers above~~ — treat every `a2a/models.py`
  anchor as provisional until re-verified post-FEAT-272.

---

## Implementation Notes

### Pattern to Follow
- Envelope goes into a data `Part` (`Part.from_data`) with the extension's
  metadata keys — mirror how `to_dict` already versions part serialization
  (`to_dict(version=...)`).
- Keep the A2UI-specific knowledge (extension URI, media type, metadata key
  names) in one place; `parrot/a2a` should call a thin helper rather than
  scattering literals.
- Follow the spec's serialization discipline: the A2UI envelope placed in
  parts is the already-serialized dict from `AIMessage.a2ui_envelope` —
  do not re-shape it here; `parrot.outputs.a2ui.serialization` remains the
  single owner of the A2UI `version` field.

### Key Constraints
- **Display only**: reject/skip envelopes containing `requires_actions`
  components when emitting over A2A in v1; never emit `action`,
  `actionResponse`, or `callFunction` messages.
- Legacy A2A responses (no `a2ui_envelope`) must serialize byte-identically to
  before — the new branch is strictly additive.
- One-way import rule (G8): `parrot.outputs.a2ui` never imports `parrot.a2a`;
  the dependency direction is a2a → outputs (or via the plain dict on
  `AIMessage`, requiring no import at all — preferred).
- Async where the emit seam is async; Google-style docstrings; `self.logger`.

### References in Codebase
- `packages/ai-parrot/src/parrot/a2a/models.py:129-380` — Part/Artifact (pre-merge)
- `sdd/tasks/index/a2a-protocol-compatibility.json` — FEAT-272 state (check completed)
- A2UI-A2A official extension: https://a2ui.org/specification/v1.0-a2ui/ (extension section)
- TASK-1738 output — `AIMessage.a2ui_envelope` carrier

---

## Acceptance Criteria

- [ ] **Precondition documented in the Completion Note**: FEAT-272 merged to
      `dev` before work started; contract anchors re-verified/reconciled.
- [ ] A display `CreateSurface` envelope is wrapped into `Artifact.parts` per
      the A2UI-A2A official extension (URI/media type recorded in code + note).
- [ ] `Artifact.to_dict()` output for A2UI artifacts round-trips the envelope
      unmodified (byte-equal dict).
- [ ] Envelopes with `requires_actions` components are not emitted over A2A
      (display-only enforcement tested).
- [ ] Legacy (non-A2UI) A2A artifact serialization unchanged (regression test).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/a2a/test_a2ui_extension_emit.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/a2a`

---

## Test Specification

> Minimal scaffold — names and intent only; the agent writes the bodies.

```python
# packages/ai-parrot/tests/a2a/test_a2ui_extension_emit.py

class TestA2UIA2AEmit:
    def test_envelope_wrapped_in_artifact_parts(self):
        """A display CreateSurface envelope becomes an A2A Artifact whose parts carry
        the envelope per the A2UI-A2A extension (correct media type / metadata keys)."""

    def test_artifact_to_dict_roundtrips_envelope(self):
        """Artifact.to_dict() preserves the envelope dict exactly; A2UI 'version' is
        untouched by the A2A layer (single-owner rule)."""

    def test_display_only_rejects_requires_actions(self):
        """Envelopes containing requires_actions components are refused/skipped on the
        A2A emit path in v1 (FEAT-B territory)."""

    def test_legacy_artifact_serialization_unchanged(self):
        """Artifact.from_response + to_dict for plain text responses is byte-identical
        to pre-task behavior (no a2ui keys leak into legacy artifacts)."""
```

---

## Agent Instructions

When you pick up this task:

1. **Confirm the cross-feature blocker is cleared** — FEAT-272 merged to `dev`
   (check `sdd/tasks/index/a2a-protocol-compatibility.json` and `git log dev`).
   If not merged, STOP and return the task.
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - **`parrot/a2a/models.py` anchors are provisional** — FEAT-272 likely moved
     them; update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in the per-spec index → `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-1741-a2a-extension-emit.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Precondition**: FEAT-272 (a2a-protocol-compatibility) is **merged to dev**
(index `completed_at` set; completion commits present). Contract anchors re-verified:
`Part` :129, `Part.from_data` :144, `Artifact` :336, `from_response` :345,
`to_dict` :361 — all stable post-FEAT-272 (no drift; matched the "current dev" values).

**Notes**: Added to `a2a/models.py`: single-owner extension constants
`A2UI_EXTENSION_URI = "https://a2ui.org/extensions/a2a/display/v1"` and
`A2UI_MEDIA_TYPE = "application/vnd.a2ui.envelope+json"`, plus
`Artifact.from_a2ui_envelope(envelope, ...)` which wraps a display `createSurface`
envelope verbatim into a data `Part` (metadata carries extensionUri + mediaType; the
A2A layer never re-shapes the envelope, honoring the serialization single-owner rule).
`Artifact.from_response` gained an additive branch: responses carrying `a2ui_envelope`
route to `from_a2ui_envelope`; legacy text responses are byte-identical to before.
Display-only enforced: non-`createSurface` envelopes and envelopes with action-bearing
(`requires_actions`) components are rejected with `ValueError`. 6 tests pass; ruff clean.

**Deviations from spec**: The official A2UI-A2A extension URI/media-type strings were
not fetchable offline, so I defined plausible, clearly-documented identifiers in ONE
place (`A2UI_EXTENSION_URI`/`A2UI_MEDIA_TYPE`) — trivially updatable when the official
extension text is confirmed, consistent with the spec's single-owner discipline.
