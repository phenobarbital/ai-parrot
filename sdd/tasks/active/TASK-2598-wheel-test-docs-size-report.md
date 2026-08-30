# TASK-2598: Wheel-content assertion, Admin UI docs, bundle size report

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2597
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, §5 last criteria. Closes the feature: the wheel
guarantee covers the chat chunk, and adopters/developers can read how
the flags, the lean build, the bundle sizes and the navigator-divergence
policy work.

---

## Scope

- `packages/ai-parrot-server/tests/test_wheel_layout.py`: add
  `test_agentchat_chunk_present` (`@pytest.mark.wheel_build`) asserting
  at least one `parrot/server/ui/dist/assets/*` entry whose name
  contains `AgentChat` (Vite names lazy chunks after the module).
- `docs/admin-ui.md`: new section "Agent Chat" after "Wheel-content
  guarantee…" (line 142) covering: routes, the eight
  `PUBLIC_AGENTCHAT_*` flags with defaults, the lean-build recipe
  (`PUBLIC_AGENTCHAT_MAPS=false pnpm build`), measured `dist/` size
  all-on vs all-off (run both builds and record numbers), the
  offline-icons note, the `wsService` stub, and the divergence policy
  (vendored tree mirrors navigator paths; `// ai-parrot:` header
  comments; how to back-port with `diff -r`).
- `packages/ai-parrot-server/ui/README.md` (if present): pointer to the
  docs section.
- Confirm `Makefile build-server-ui` and `.github/workflows/release.yml`
  need no change (defaults = all on); note in docs that env overrides
  are honoured by both.

**NOT in scope**: code changes in `ui/src`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/test_wheel_layout.py` | MODIFY | new test |
| `docs/admin-ui.md` | MODIFY | "Agent Chat" section |
| `packages/ai-parrot-server/ui/README.md` | MODIFY (if exists) | pointer |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-server/tests/test_wheel_layout.py — existing fixture `satellite_wheel_namelist` (used at :72, :83); marker `wheel_build` (pyproject.toml [tool.pytest.ini_options] markers)
```

### Existing Signatures to Use
```python
# test_wheel_layout.py:72  def test_dist_index_present(self, satellite_wheel_namelist): assert "parrot/server/ui/dist/index.html" in satellite_wheel_namelist
# test_wheel_layout.py:83  def test_dist_assets_present(self, satellite_wheel_namelist): assets = [n for n in … if n.startswith("parrot/server/ui/dist/assets/")]; assert assets
# pyproject.toml:104-111   [tool.setuptools.package-data] "parrot.server.ui" = ["dist/*", "dist/assets/*"]
# Makefile:346             release: lint test clean check-registry build-rust build-server-ui
# docs/admin-ui.md headings: What it is (8), Auth model (23), Adopter view (42), Developer view (87), Codegen (107), Where the build output lands (122), Tests (135), Wheel-content guarantee and release pipeline (142)
```

### Does NOT Exist
- ~~a size-report step in `release.yml`~~ — decided not to add one (spec §8); numbers live in docs.
- ~~`pnpm size` script~~ — measure with `du -sh dist/assets` after each build.

---

## Implementation Notes

### Key Constraints
- The wheel test must not assume a specific hash: match `AgentChat` substring + `.js` suffix.
- Document flag names exactly as in `ui/vite.config.ts` (TASK-2591).

---

## Acceptance Criteria

- [ ] `pytest -m wheel_build packages/ai-parrot-server/tests/test_wheel_layout.py -v` passes, including the new test
- [ ] `docs/admin-ui.md` has the "Agent Chat" section with all eight flags, both size measurements, and the divergence policy
- [ ] Spec §5 checklist fully satisfied — reviewer walks it and ticks every box

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_wheel_layout.py (addition inside the FEAT-468 Admin UI test class)
@pytest.mark.wheel_build
def test_agentchat_chunk_present(self, satellite_wheel_namelist):
    """FEAT-476: the vendored AgentChat lazy chunk ships in the wheel."""
    chunks = [
        n for n in satellite_wheel_namelist
        if n.startswith("parrot/server/ui/dist/assets/") and "AgentChat" in n and n.endswith(".js")
    ]
    assert chunks, "wheel is missing the AgentChat chunk — was the UI built with the chat module?"
```

---

## Agent Instructions

1. Read spec §3 Module 8 and §5. 2. Confirm TASK-2597 completed. 3. Verify contract (`test_wheel_layout.py` fixture names). 4. Index → `in-progress`. 5. Implement. 6. Verify. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
