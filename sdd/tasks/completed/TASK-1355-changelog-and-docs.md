# TASK-1355: CHANGELOG, Migration Guide & Documentation

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1354
**Assigned-to**: unassigned

---

## Context

Document the breaking changes and provide a migration guide for users
upgrading from monolithic `ai-parrot` to the split packages. This is
the final task before the PR.

Implements **Spec Module 14**.

---

## Scope

- Update `CHANGELOG.md` with:
  - Breaking: `pywa`, `aiogram`, `azure-teambots`, `mautrix` no longer
    installed with `ai-parrot` base.
  - Migration: `pip install ai-parrot-integrations[<channel>]` for each
    channel needed.
  - Breaking: `from parrot.integrations.oauth2.X` →
    `from parrot.auth.oauth2.X`
  - Breaking: `from parrot.integrations.zoom.client` →
    `from parrot_tools.zoom.client`
  - New: granular extras
    `[slack|telegram|msteams|whatsapp|matrix|voice|messaging|all]`
- Create `docs/migration/feat-202-ai-parrot-integrations.md` with
  detailed migration guide.
- Update satellite `packages/ai-parrot-integrations/README.md` with
  install instructions and extras reference.

**NOT in scope**: Updating CI/CD pipelines (open question).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `CHANGELOG.md` | MODIFY | Add breaking changes + migration section |
| `docs/migration/feat-202-ai-parrot-integrations.md` | CREATE | Detailed migration guide |
| `packages/ai-parrot-integrations/README.md` | MODIFY | Full install + usage docs |

---

## Acceptance Criteria

- [ ] CHANGELOG.md has entry for FEAT-202 with breaking changes
- [ ] Migration guide exists at `docs/migration/feat-202-ai-parrot-integrations.md`
- [ ] README.md in satellite package has install examples for each extra
- [ ] Guide covers: oauth2 path change, zoom path change, missing SDK errors

---

## Completion Note

*(Agent fills this in when done)*

---

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-28
**Notes**: Created `CHANGELOG.md` at repo root with breaking changes, new features, and non-breaking changes. Created `docs/migration/feat-202-ai-parrot-integrations.md` with detailed upgrade instructions covering oauth2 path changes, zoom path changes, extras reference, matrix hook changes, ChannelRegistry usage, and CI/CD changes. The satellite README.md already had full install instructions from TASK-1344.
**Deviations from spec**: none
