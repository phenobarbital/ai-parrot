# HOTFIX-5baa3dae9606-2: Replace the per-module sidebar listing with one API Reference index page

**Feature**: techwiki-page-names-sidebar (BRIEF-5baa3dae9606)
**Spec**: sdd/briefs/techwiki-page-names-sidebar.brief.md
**Status**: done
**Priority**: medium
**Estimated effort**: S
**Depends-on**: HOTFIX-5baa3dae9606-1
**Assigned-to**: unassigned

## Context
`write_navigation` lists every page of every section in `_Sidebar.md`, so a full bundle produces a 216 KB
sidebar with 3078 API module entries that GitHub renders on every wiki page. See the brief's Root cause
section, item 4. This task relies on `BundlePage.module` introduced by HOTFIX-5baa3dae9606-1.

## Scope
- In `bundle.py`, add `_reference_index_page(cfg, generated) -> BundlePage` that returns one generated
  page with `source=None`, `module=None`, `section=cfg.reference_section`, `title=cfg.reference_section`,
  `name=page_name(None, cfg.reference_section)` (→ `API-Reference` by default) and a plain-Python Markdown
  body (no Jinja): `# <section>`, one `## <top-level package>` heading per distinct first dotted segment
  of `page.module`, and under it one `- [[<page.name>]]` line per module page, both in sorted order.
  `assemble` appends it right after the generated pages when `with_api` is true and at least one page was
  generated, so collision detection (an authored top-level page titled `API Reference`) and the manifest
  cover it. `_manifest_entries` records it as `{"id": "index:<name>", "name": <name>, "section": "api",
  "kind": "index"}`; `_ref_id` returns `index:<name>` for a generated page without a module.
- In `write_navigation`, build the sidebar rows from the same section grouping as Home but, for the
  section named `cfg.reference_section`, keep only pages whose `module is None` (the index page). Home keeps
  the full per-section page counts.
- Tests in `test_techwiki_bundle.py`:
  - `write_bundle` over `api_repo`: `_Sidebar.md` contains `[[API-Reference]]` and no
    `[[API-Reference-samplepkg.` link; `API-Reference.md` exists, links every generated page, and is in
    the manifest with `kind == "index"`.
  - `test_every_rewritten_link_resolves_in_the_manifest` still passes (sidebar + index links resolve).
  - An authored top-level page `wiki/api-reference.md` titled `API Reference` is reported as a collision
    with `index:API-Reference`.
  - `assemble(..., with_api=False)` produces no index page.

**NOT in scope**: changing `home.md.j2` / `sidebar.md.j2`; paginating the index; the ADR or authored
sections of the sidebar.

## Files to Create / Modify
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py`
- MODIFY `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py`

## Codebase Contract
- Verified: `bundle.py:175-254` `assemble(cfg, root, *, release, commit, with_api)`; generated pages are
  appended at `bundle.py:205-212`; collision detection follows at `bundle.py:214-230`; manifest at
  `bundle.py:232-237`.
- Verified: `bundle.py:283-301` `write_navigation(pages, report, cfg, out)` groups `pages` by
  `page.section` and renders `home.md.j2` and `sidebar.md.j2` from the same `section_rows`.
- Verified: `templates/sidebar.md.j2` renders `- [[{{ page.name }}]]` per page of each section.
- Verified: `bundle.py:20` `_RESERVED_NAMES` (`Home`, `_Sidebar`, `techwiki-report`, `techwiki-manifest`) used by the reserved-name
  check at `bundle.py:223-230`.
- Verified: `test_techwiki_bundle.py:205-218` `test_every_rewritten_link_resolves_in_the_manifest`
  scans every written `*.md` including `_Sidebar.md`.
- Verified (after HOTFIX-5baa3dae9606-1): `BundlePage.module: str | None`.
- Does NOT exist: `_reference_index_page`, any index page, a `kind: index` manifest entry.

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_bundle.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#assemble",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#write_navigation",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#_manifest_entries",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#_ref_id"
  ]
}
```

## Acceptance Criteria
- A full local bundle writes an `_Sidebar.md` under 10 KB whose reference section is the single link
  `[[API-Reference]]`, and an `API-Reference.md` that links all generated module pages.
- Every `[[Page]]` in `_Sidebar.md` and `API-Reference.md` is a manifest name.
- The techwiki test files pass; `ruff check` passes on the changed files.

## Validation Commands
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`

## Completion Note
Implemented. `assemble` appends `_reference_index_page(cfg, generated)` (source None, module None, name from
`page_name(None, cfg.reference_section)`) whenever API pages were generated; the manifest records it as
`{"id": "index:API-Reference", "kind": "index"}` and `_ref_id` returns `index:<name>` for it, so the existing
collision and reserved-name checks cover it. `write_navigation` renders Home from the full section rows and the
sidebar from rows where the reference section keeps only `module is None` pages. Tests: 75 passed across the
four techwiki test files; ruff clean. Full local bundle from the branch: `_Sidebar.md` 18 KB (was 216 KB),
`API-Reference.md` 164 KB linking 3077 module pages under 7 top-level packages, 3376 files, 0 forbidden
names. Seat: native (main session).
