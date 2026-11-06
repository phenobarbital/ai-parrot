# HOTFIX-5baa3dae9606-1: Sanitize artifact-forbidden characters out of techwiki page names

**Feature**: techwiki-page-names-sidebar (BRIEF-5baa3dae9606)
**Spec**: sdd/briefs/techwiki-page-names-sidebar.brief.md
**Status**: done
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
The 2.1.0 `techwiki.yml` release run failed in `actions/upload-artifact` because generated API pages are
named `API-Reference-Reference:-<module>.md` and 26 authored pages carry a colon from their title. The
upload refuses `" : < > | * ? \r \n`, so the `publish` job never ran and the GitHub wiki is empty. See the
brief's Root cause section, items 1–3.

## Scope
- In `naming.py`, add a module constant `FORBIDDEN_NAME_CHARS = '":<>|*?\r\n'` and make `page_name`
  replace each of those characters with a space in both `title` and `section` before whitespace is
  collapsed into `-`, exactly where `/` and `\` are already replaced. Keep the empty-title and
  literal-hyphen rules as they are (the hyphen check still runs on the raw title). Document the rule in
  the docstring (upload-artifact / NTFS-safe names).
- In `api.py`, `render_module` titles the page with the bare module name (`title = module_name`) and
  takes a `section: str = "API Reference"` keyword argument used for `RenderedPage.section`; `_generate`
  passes `section=cfg.reference_section`. The template keeps rendering `# {{ title }}`.
- In `bundle.py`, add `module: str | None = None` as the last field of `BundlePage`; `_generated_pages`
  sets it from `RenderedPage.module`; `_manifest_entries` and `_ref_id` build `ref:<module>` from
  `page.module` instead of stripping a title prefix.
- Tests:
  - `test_techwiki_naming.py`: parametrized test that each character in `FORBIDDEN_NAME_CHARS` is
    replaced (e.g. `page_name("Server & APIs", "Server Layer: BotManager")` ==
    `"Server-&-APIs-Server-Layer-BotManager"`; `page_name(None, 'a"b<c>d|e*f?g')` == `"a-b-c-d-e-f-g"`),
    and that the result never contains any forbidden character.
  - `test_techwiki_bundle.py`: update the three pinned names (`API-Reference-samplepkg.core`), make the
    `_Gen` stub use `title = "x.y"`, make the collision test write `# samplepkg.core` under the `ref`
    section, and add a test that `write_bundle` over `api_repo` produces no file whose name contains a
    forbidden character.
  - `test_techwiki_api.py`: assert a rendered page has `title == module name` and
    `section == cfg.reference_section` when a custom section is configured.
- Update the comment on `sdd/specs/github-wiki-technical-reference.spec.md:307` to
  `# "parrot.memory.compaction"`.

**NOT in scope**: the sidebar index page (HOTFIX-5baa3dae9606-2); editing any authored page under
`wiki/`; `.github/workflows/techwiki.yml`; ledger issues 0891861cb3c1, b9829d5f3a2b, 5af0e518b2e8.

## Files to Create / Modify
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/naming.py`
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/api.py`
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py`
- MODIFY `packages/ai-parrot/tests/sdd/test_techwiki_naming.py`
- MODIFY `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py`
- MODIFY `packages/ai-parrot/tests/sdd/test_techwiki_api.py`
- MODIFY `sdd/specs/github-wiki-technical-reference.spec.md`
- MODIFY `packages/ai-parrot/tests/sdd/fixtures/techwiki_golden/samplepkg.md` and `samplepkg.core.md` (H1 loses the `Reference: ` prefix)

## Codebase Contract
- Verified: `naming.py:16` `def page_name(section: str | None, title: str) -> str`; `naming.py:30`
  empty-title raise; `naming.py:31-35` literal-hyphen raise; `naming.py:38` `/` and `\` replaced by spaces.
- Verified: `api.py:430` `def render_module(`; `api.py:462` `title = f"Reference: {module_name}"`;
  `api.py:466` `section="API Reference"`; `api.py:547` `render_module(module, template=template,
  source_url=cfg.source_url, release=release, root=root)` inside `_generate`.
- Verified: `api.py:23-29` `@dataclass class RenderedPage` with fields `module, section, title, body`.
- Verified: `bundle.py:23-31` `@dataclass class BundlePage` with fields `source, section, title, name, body`.
- Verified: `bundle.py:148-158` `_generated_pages` builds `BundlePage(None, page.section, page.title,
  page_name(page.section, page.title), page.body)`.
- Verified: `bundle.py:166` and `bundle.py:259` strip `"Reference: "` from the title.
- Verified: `config.py:34` `reference_section: str = "API Reference"`.
- Verified: `templates/module.md.j2:95` `# {{ title }}`.
- Verified: tests pin the old name at `test_techwiki_bundle.py:151`, `:200`, `:228`, `:231`.
- Does NOT exist: `BundlePage.module`, `FORBIDDEN_NAME_CHARS`, a `section` parameter on `render_module`.

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/naming.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/api.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_naming.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_bundle.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_api.py", "action": "MODIFY"},
    {"path": "sdd/specs/github-wiki-technical-reference.spec.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/naming.py#page_name",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/api.py#render_module",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#BundlePage",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#_generated_pages",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#_manifest_entries",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#_ref_id"
  ]
}
```

## Acceptance Criteria
- `page_name` never returns a name containing any of `" : < > | * ? \r \n`; titles keep those characters.
- A generated page for `parrot.memory.compaction` is named `API-Reference-parrot.memory.compaction` and
  its manifest id is `ref:parrot.memory.compaction`; `[Core](ref:samplepkg.core)` rewrites to
  `[[API-Reference-samplepkg.core]]`.
- A full local bundle (`parrot sdd techwiki bundle --release 2.1.0 --strict`) writes no file whose name
  contains a forbidden character (previously 3104 of 3376 did).
- The techwiki test files pass; `ruff check` passes on the changed files.

## Validation Commands
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_techwiki_naming.py packages/ai-parrot/tests/sdd/test_techwiki_bundle.py packages/ai-parrot/tests/sdd/test_techwiki_api.py packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`

## Completion Note
Implemented. `page_name` now translates `/ \ " : < > | * ? \r \n` to a space before collapsing to `-` (new
`FORBIDDEN_NAME_CHARS`, raises when nothing usable remains); `render_module` titles pages with the bare module
name and takes `section=cfg.reference_section`; `BundlePage.module` added and `_manifest_entries`/`_ref_id`
derive `ref:<module>` from it. Golden fixtures regenerated (H1 lost the `Reference: ` prefix); spec line 307
updated. Tests: 72 passed across the four techwiki test files; ruff clean. Full local bundle from the branch:
3375 files, 0 names with forbidden characters (was 3104). Commit 994c116e27. Seat: native (main session).
