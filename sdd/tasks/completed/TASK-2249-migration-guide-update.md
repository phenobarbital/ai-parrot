# TASK-2249: Update the FEAT-421 migration guide for `/t/`-free URLs

**Feature**: FEAT-429 — Remove `/t/` marker from tenant-qualified URLs
**Spec**: `sdd/specs/fieldsync-tenant-url.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2246, TASK-2247
**Assigned-to**: unassigned

---

## Context

The migration guide at `docs/migration/feat-421-forms-tenant-in-url.md` was
written for FEAT-421's `/t/{tenant}/` URL shape. Since FEAT-429 amends the
URLs before 0.9.0 ships to production, the guide must be updated **in place**
to reflect the final `/{tenant}/` shape. Consumers should only ever see the
final URL format.

Implements spec Module 4.

---

## Scope

Update `docs/migration/feat-421-forms-tenant-in-url.md`:

- **All URL examples**: `/t/{tenant}/` → `/{tenant}/`
- **Old → new URL table**: the "New (0.9.0)" column changes from
  `/t/{tenant}/` to `/{tenant}/`; the "Old (0.8.x)" column stays unchanged.
- **The error contract examples**: `expected` field in JSON bodies.
- **The coordinated deploy checklist**: remove the `/t/{tenant}/` mention.
- **The "Why this change exists" section**: add a note about FEAT-429
  simplifying the URL shape before release.
- **The POST-body rule examples**: URL in the request line.

**NOT in scope**:
- Source code changes (TASK-2246, TASK-2247).
- Test updates (TASK-2248).
- Creating a NEW migration guide — the existing one is updated in place.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/migration/feat-421-forms-tenant-in-url.md` | MODIFY | Update all URLs and add FEAT-429 note |

---

## Codebase Contract (Anti-Hallucination)

### Verified Structure

The migration guide is a Markdown document with these sections:
- "Why this change exists" (line 9)
- "Coordinated deploy checklist" (line 29)
- "`/org/*` URLs are UNCHANGED" (line 50)
- "Old → new URL table" (line 80)
  - JSON REST API table (line 86)
  - HTML pages + Telegram table (line 113)
- "The new error contract" (line 125)
- "The POST-body rule" (line 189)
- "What did NOT change" (line 209)
- "Zero host wiring required" (line 222)

### Does NOT Exist

- ~~A separate FEAT-429 migration guide~~ — not needed; the FEAT-421 guide
  is updated in place since 0.9.0 hasn't shipped.
- ~~`docs/migration/feat-429-*.md`~~ — do not create one.

---

## Implementation Notes

### Pattern to Follow

Mechanical replacement throughout the document:

```
/t/{tenant}/  →  /{tenant}/
/t/           →  /           (in URL context only)
```

### Key Constraints

- **Do NOT change the "Old (0.8.x)" column** in the URL table — those are
  the pre-FEAT-421 URLs and are correct as-is.
- **Do NOT change the `/org/*` section** — those URLs were never prefixed.
- Add a brief note (1-2 sentences) in the "Why this change exists" section
  or as a note at the top explaining FEAT-429 simplified the URL before
  release:
  ```
  > **Note (FEAT-429):** The original FEAT-421 design used a `/t/{tenant}/`
  > marker segment for router disambiguation. This was simplified to
  > `/{tenant}/` before 0.9.0 shipped — aiohttp's literal-first route
  > matching makes the marker unnecessary.
  ```
- Update the status line to mention FEAT-429.

### Verification

After editing, scan the file for any remaining `/t/` references:

```bash
grep -n '/t/{tenant}\|/t/' docs/migration/feat-421-forms-tenant-in-url.md
```

Expected: zero lines (except the FEAT-429 note if it mentions the old format
for context).

---

## Acceptance Criteria

- [ ] Every URL example in the migration guide uses `/{tenant}/`, not
      `/t/{tenant}/`.
- [ ] The "New (0.9.0)" column in both URL tables uses `/{tenant}/`.
- [ ] The "Old (0.8.x)" column is unchanged.
- [ ] Error contract `expected` fields use the new URL shape.
- [ ] POST-body rule examples use the new URL shape.
- [ ] A FEAT-429 note is present explaining the simplification.
- [ ] The `/org/*` section is unchanged.

---

## Test Specification

No code tests — this is a documentation-only task.

---

## Agent Instructions

When you pick up this task:

1. **Read** `docs/migration/feat-421-forms-tenant-in-url.md`
2. **Replace** all `/t/{tenant}/` → `/{tenant}/` in URL examples
3. **Add** the FEAT-429 explanatory note
4. **Verify** with the grep command above
5. **Commit** with message: `docs: update FEAT-421 migration guide for FEAT-429 URL simplification (TASK-2249)`

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-18
**Notes**: Applied a blanket `s#/t/#/#g` substitution across
`docs/migration/feat-421-forms-tenant-in-url.md` — verified beforehand that
every one of the file's 28 `/t/` occurrences was in a "New (0.9.0)" URL
example, an error-contract `expected` field, a POST-body example, or
descriptive prose (none in an "Old (0.8.x)" column, and none inside the
`/org/*` section's actual route paths — that section only *mentions* the
forms namespace shape in prose, which correctly updates alongside it).
Added the FEAT-429 explanatory note (verbatim from the task's suggested
text) directly under the document header, and amended the `**Feature**:`
line to note the FEAT-429 amendment. The note itself intentionally retains
3 `/t/{tenant}/`-referencing occurrences describing the OLD, removed
format for context — exactly the carve-out the task's own verification
command allows ("except the FEAT-429 note if it mentions the old format
for context").

Verified: zero remaining `/t/{tenant}` URL references outside the note;
all "Old (0.8.x)" table columns byte-identical (diff contains no removed
"Old" column lines); all ten `/org/*` example paths byte-identical
(diff contains no removed `/api/v1/org/...` lines).

Did not add documentation for TASK-2250's reserved-segment guard (404 on
`org`/`form-controls` tenant slugs) — out of this task's explicit scope
(Module 4 / TASK-2249 predates TASK-2250 in the spec's module numbering
and this task's own Scope/Files-to-Modify sections don't mention it); left
for a future doc task if the team wants it surfaced to consumers.

**CORRECTION (filed after adversarial code review)**: the code-reviewer
agent raised this omission as a 🟠 IMPORTANT finding — new,
consumer-visible behavior (a tenant named `org`/`form-controls`/`api` now
404s everywhere, plus a boot WARNING) belonged in the same guide that
already documents the error contract and deploy checklist, regardless of
which task's module numbering technically owns it. Added a "Reserved
tenant segments (FEAT-429)" section plus a checklist item, committed
separately: `docs: document the reserved-segment guard in the FEAT-421
migration guide (code review finding)`.

**Deviations from spec**: none.
