# TASK-5246: MatrixCarrier — carry `RoostMessage.hops` in `m.parrot.roost` events

**Feature**: FEAT-827 fixgroup-742a9ada6cba
**Spec**: `sdd/specs/fixgroup-742a9ada6cba.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:2c7a156eb239`

## Context
Implements M1 of the spec. `RoostEventContent` has no `hops` field, so a Roost message that crosses a
Matrix room arrives with `hops == 0` and the receiver's hop-limit check can never trip.

## Scope
- Add `hops: int = Field(default=0, ge=0)` to `RoostEventContent`.
- `MatrixCarrier.to_content` writes `msg.hops`; `MatrixCarrier.from_content` passes `hops=parsed.hops`.
- Tests: round trip keeps `hops`; legacy content without the key parses as 0; negative `hops` rejected.

**NOT in scope**: `tokens` / `permission_context` / `auth_token` over Matrix; any change to `crew/`.

## Files to Create / Modify
- `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py` (modify — `RoostEventContent` only)
- `packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/carrier.py` (modify — `to_content`, `from_content`)
- `packages/ai-parrot-integrations/tests/test_matrix_roost_carrier.py` (modify — add tests)

## Codebase Contract (Anti-Hallucination)
Verified against `origin/dev` @ `927f9ab4b8`.

**Verified Imports**
- `from parrot.integrations.matrix.events import ParrotEventType, RoostEventContent`
- `from parrot.integrations.matrix.roost import MatrixCarrier`
- `from parrot.roost.messages import AgentAddress, FailureInfo, LocalEnvelope, RoostMessage`

**Existing Signatures**
- `class RoostEventContent(BaseModel)` (events.py:285) — fields `body, performative, protocol, conversation_id, message_id, in_reply_to, sender, receivers, capability_filter, content, content_ref, envelope, failure`.
- `TaskEventContent.hops: int = Field(default=0, ge=0)` (events.py:128) — the precedent for the field definition; `Field` is already imported in events.py.
- `MatrixCarrier.to_content(msg: RoostMessage, *, body: str) -> RoostEventContent` (carrier.py:185, staticmethod).
- `MatrixCarrier.from_content(content: Dict[str, Any], *, event_id: str) -> RoostMessage` (carrier.py:220, staticmethod).
- `RoostMessage.hops: int = 0` (parrot/roost/messages.py).
- Test helpers `_msg(**kw)` and `_client()` in `test_matrix_roost_carrier.py` (lines 15, 28).

**Does NOT Exist**
- `RoostEventContent.hops`, `RoostEventContent.tokens`.

## Acceptance Criteria
Spec AC-1, AC-6.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/test_matrix_roost_carrier.py -q`

Run from the worktree root with
`PYTHONPATH=$PWD/packages/ai-parrot/src:$PWD/packages/ai-parrot-integrations/src`.

## Test Specification
- `test_round_trip_keeps_hops`: `from_content(to_content(_msg(hops=3), body="b").model_dump(), event_id="$e").hops == 3`.
- `test_legacy_content_without_hops_defaults_to_zero`: drop the `hops` key from the dumped content → `hops == 0`.
- `test_negative_hops_rejected`: `RoostEventContent(..., hops=-1)` raises `ValidationError`.

## Agent Instructions
Lint the changed files with `ruff check` before committing. Stage only the three files listed above.

## Completion Note

**Completed by**: Claude Code `/sdd-fix` session (`agent:sdd-fix:b73eac7f`)
**Date**: 2026-11-06
**Notes**: Implemented in `b82ec0fe5f`. `RoostEventContent.hops` (default 0, `ge=0`); `MatrixCarrier.to_content`
writes it and `from_content` reads it. `test_matrix_roost_carrier.py` + `test_matrix_swarm_events.py`: 16 passed;
`black --check` clean. `ruff check` reports one pre-existing F401 in `events.py` (`SerializableAttrs` in the
mautrix availability probe, line 15) — untouched here, left to the feature lint pass.

**Deviations from spec**: none.
