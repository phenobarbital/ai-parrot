# TASK-5128: Studio cross-spec contract and docs — required schema 1..9

**Feature**: FEAT-794 — Prompt Library — writable again, with manual order
**Spec**: `sdd/specs/prompt-library-writable-sort-order.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview item 4 and Module 4. The Studio cross-spec contract row X1 is byte-identical in three specs and pinned
by tests; it and `docs/agentstudio/db-storage.md` say the `database` backend requires versions 1..8. With `0009` that
becomes 1..9, and X1 must name `navigator.prompt_library` as an existing, non-Studio table that `0009` extends in place.

---

## Scope

- Edit X1 in `sdd/specs/agentstudio-db-storage.spec.md`, then copy the identical row into
  `agentstudio-tenant-visibility.spec.md` and `agentstudio-host-toolkits.spec.md`:
  - "required versions 1..8 … covers 1..8" → "1..9";
  - list `navigator.prompt_library` as **existing**, extended in place by `0009` (`agent_id`, `sort_order`);
  - add `0009` to the migrations column.
- `agentstudio-db-storage.spec.md:1339`: `STUDIO_SCHEMA_REQUIRED = 9`.
- `docs/agentstudio/db-storage.md:52`: `STUDIO_SCHEMA_REQUIRED = 9` (migrations 0001-0009), and "apply 0009 first".
- Rename and update the two pinned tests in `test_feat605_contract_doc.py`.

**NOT in scope**: code, migrations, any other X row.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/specs/agentstudio-db-storage.spec.md` | MODIFY | X1 row (:1952) + required version (:1339) |
| `sdd/specs/agentstudio-tenant-visibility.spec.md` | MODIFY | X1 row (:1539) |
| `sdd/specs/agentstudio-host-toolkits.spec.md` | MODIFY | X1 row (:1193) |
| `docs/agentstudio/db-storage.md` | MODIFY | Required schema paragraph (:52) |
| `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` | MODIFY | Pinned tests (:98, :103) |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py
def test_cross_spec_contract_identical_in_the_three_specs():   # :87 — the three X1 rows must stay byte-identical
@pytest.mark.parametrize("spec", SPECS)
def test_required_schema_version_is_eight(spec):              # :98
    assert "required versions 1..8 for the `database` backend" in _contract(spec)
    assert "1..5" not in _contract(spec)
def test_storage_spec_states_required_eight():                # :103
    assert "STUDIO_SCHEMA_REQUIRED = 8" in text and "STUDIO_SCHEMA_REQUIRED stays 5" not in text
```

Verbatim anchors (each occurs once per file):
- X1 row starts with `| X1 | Tables \`navigator.ai_agents\`` — `agentstudio-db-storage.spec.md:1952`,
  `agentstudio-tenant-visibility.spec.md:1539`, `agentstudio-host-toolkits.spec.md:1193`.
- `- **Required version**: \`STUDIO_SCHEMA_REQUIRED = 8\`` — `agentstudio-db-storage.spec.md:1339`.
- `**Required schema version.** \`STUDIO_SCHEMA_REQUIRED = 8\`` — `docs/agentstudio/db-storage.md:52`.

### Does NOT Exist
- ~~A fourth copy of X1~~: only these three specs carry it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/specs/agentstudio-db-storage.spec.md", "action": "MODIFY"},
    {"path": "sdd/specs/agentstudio-tenant-visibility.spec.md", "action": "MODIFY"},
    {"path": "sdd/specs/agentstudio-host-toolkits.spec.md", "action": "MODIFY"},
    {"path": "docs/agentstudio/db-storage.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit X1 once, in `agentstudio-db-storage.spec.md` — *why*: one source avoids drift between the copies.
2. Copy that exact row over X1 in the other two specs — *why*: `test_cross_spec_contract_identical_in_the_three_specs`.
3. Update `:1339` and the doc paragraph — *why*: spec AC5.
4. Rename and update the two pinned tests — *why*: they assert the old number.

### X1 row (MODIFY, all three specs)
```text
# In the Tables cell, after "the **existing** `navigator.ai_skills_catalog` extended in place (…)", add:
#   "; the **existing** `navigator.prompt_library` (not Studio-owned) extended in place by 0009 (adds `agent_id`,
#   `sort_order`)"
# In the migrations cell: "P2 (migrations 0006–0008, M11/M12)" → also name "0009 (FEAT-794)".
# In the rules cell: "required versions 1..8 for the `database` backend (phase 2 ships in the same release;
#   `parrot-studio-migrate --verify` covers 1..8)" → "1..9" in both places.
# FILL IN: exact wording — bounded by "byte-identical in the three specs" and by the tests below
```

### `test_feat605_contract_doc.py` (MODIFY)
```python
@pytest.mark.parametrize("spec", SPECS)
def test_required_schema_version_is_nine(spec):
    assert "required versions 1..9 for the `database` backend" in _contract(spec)
    assert "1..5" not in _contract(spec) and "1..8" not in _contract(spec)


def test_storage_spec_states_required_nine():
    text = (ROOT / "sdd" / "specs" / "agentstudio-db-storage.spec.md").read_text(encoding="utf-8")
    assert "STUDIO_SCHEMA_REQUIRED = 9" in text and "STUDIO_SCHEMA_REQUIRED = 8" not in text
```
**Why**: the second assertion in each test catches a copy left on the old number.

### FILL IN checklist
- [ ] X1 wording — bounded by byte-identity and the two tests
- [ ] `STUDIO_SCHEMA_REQUIRED = 8` gone from `agentstudio-db-storage.spec.md` (check for other mentions with `grep`)

---

## Acceptance Criteria

- [ ] The three X1 rows are byte-identical and say 1..9 (spec AC5)
- [ ] `docs/agentstudio/db-storage.md` says `STUDIO_SCHEMA_REQUIRED = 9` (spec AC5)
- [ ] `test_feat605_contract_doc.py` passes

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug prompt-library-writable-sort-order --feature-id FEAT-794`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the anchors** before editing
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5128 prompt-library-writable-sort-order verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-opus-5-5 (interactive session, Emmanuel Arroyo)
**Date**: 2026-11-03
**Notes**: X1 edited once in `agentstudio-db-storage.spec.md` and copied byte-identical into the other two specs: it now
lists `navigator.prompt_library` (not Studio-owned) as extended in place by 0009, names migration 0009 (FEAT-794) and
says 1..9 in both places. `:1339` says `STUDIO_SCHEMA_REQUIRED = 9`. `docs/agentstudio/db-storage.md` says 9 at `:52`,
and the two other "0001-0008" mentions (`:112`, `:128`) now say 0001-0009, plus one bullet on what 0009 does. The two
pinned tests are renamed `_nine` and also reject a leftover "1..8" / "= 8". Red first: 4 failed, then
`pytest packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py -q` → 52 passed, 1 failed.

The 1 failure is pre-existing and out of scope: `test_changelog_lists_the_plain_host_behaviour_changes` fails the same
way on `dev` (the v2.0.0 release emptied `## [Unreleased]` in `CHANGELOG.md`; the test also pins "required migration
level is 8"). Not touched: `CHANGELOG.md` is not in this task's files.

**Deviations from spec**: the two extra "0001-0008" lines in the doc (`:112`, `:128`) were updated too, so the doc does
not contradict itself; same file the task lists.
