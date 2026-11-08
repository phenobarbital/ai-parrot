# HOTFIX-93f079cc8e3f-1: Unlink generated `ref:` links to modules without a page; never rewrite the index

**Feature**: techwiki-unlinked-generated-refs (BRIEF-93f079cc8e3f)
**Spec**: sdd/briefs/techwiki-unlinked-generated-refs.brief.md
**Status**: done
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
After FEAT-818 the strict bundle on `dev` exits 1 with 301 dangling rows: 300 are re-export links from
generated pages to modules that legitimately have no page (import shims without `__all__`), and 1 is the
reference index page being link-rewritten although its hrefs are final. See the brief.

## Scope
- `naming.py`: add a module-level sentinel `UNLINK = object()` (documented: "resolver result meaning: drop
  the link, keep its text") and widen the resolver type to `Callable[[str], str | None | object]`. In
  `rewrite_links.replace`, after `page = resolver(base)`: `None` → unchanged (as today); `UNLINK` → return
  `match.group(1)` (the link text only, fragment discarded); otherwise the Markdown link as today.
- `bundle.py`:
  - `BundleReport` gains `unlinked: list[dict[str, str]] = field(default_factory=list)` after `dangling`.
    `ok()` is unchanged.
  - In `assemble`'s rewrite loop: `if page.source is None and page.module is None: continue` (the index
    page), with a comment. In `resolve`, when `page.source is None` and the target starts with `ref:` and
    is not in the manifest: append `{"source": origin, "target": target}` to `report.unlinked` and return
    `UNLINK`. Every other branch is unchanged (authored/ADR unresolved → dangling; generated relative →
    dangling; `index:` targets resolve through the manifest).
- Tests:
  - `test_techwiki_naming.py`: `rewrite_links("[x](ref:gone) [y](a.md#f)", lambda t: UNLINK)` ==
    `"x y"`; a resolver returning `None` still leaves the link untouched.
  - `test_techwiki_bundle.py`: rewrite `test_unresolvable_links_in_a_generated_page_are_dangling` so
    `ref:samplepkg.gone` is asserted in `report.unlinked` (and the page body contains `Gone` with no
    `](ref:` and no `](`), while `../other.md` stays in `report.dangling` and `report.ok()` is False.
    Add `test_reference_index_page_is_never_rewritten`: monkeypatch `_generated_pages` to return a page
    with `module="samplepkg.md"` (so the index links `API-Reference-samplepkg.md`); assert
    `report.dangling == []`, `report.ok()`, and the index body still contains
    `[samplepkg.md](API-Reference-samplepkg.md)`. Add `test_unlinked_rows_reach_the_report_payload`:
    `report_payload(report)["unlinked"]` is a list and the written `techwiki-report.json` has the key.
- No change to templates, the spec, `techwiki.yml` or any authored page.

**NOT in scope**: generating pages for modules without public members; the `parrot.auth` `__all__`
gap; the `techwiki check` command.

## Files to Create / Modify
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/naming.py`
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py`
- MODIFY `packages/ai-parrot/tests/sdd/test_techwiki_naming.py`
- MODIFY `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py`

## Codebase Contract
- Verified: `naming.py:115` `def rewrite_links(text: str, resolver: Callable[[str], str | None]) -> str`;
  `naming.py:135-136` `page = resolver(base)` / `if page is None:`.
- Verified: `bundle.py:36` `class BundleReport`; `bundle.py:46` `dangling: list[dict[str, str]]`;
  `bundle.py:48` `def ok(self)`.
- Verified: `bundle.py:280` `for page in pages:` (rewrite loop); `bundle.py:282` `def resolve(target, page=page)`;
  `bundle.py:297` and `:303` `report.dangling.append({"source": origin, "target": target})`;
  `bundle.py:306` `page.body = rewrite_links(page.body, resolve)`.
- Verified: `test_techwiki_bundle.py:318` `test_generated_page_ref_links_are_rewritten`;
  `:335` `test_unresolvable_links_in_a_generated_page_are_dangling` (monkeypatches
  `bundle_module._generated_pages`).
- Verified: `BundlePage` fields `source, section, title, name, body, module`; the index page is built by
  `_reference_index_page` with `source=None` and no `module`.
- Does NOT exist: `naming.UNLINK`, `BundleReport.unlinked`.

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/naming.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_naming.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_bundle.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/naming.py#rewrite_links",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#BundleReport",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#assemble"
  ]
}
```

## Acceptance Criteria
- `python -m parrot.sdd.scripts.techwiki_bundle --root . --release dev --json --strict` on the branch
  exits 0 with `"dangling": []` and a non-empty `"unlinked"` list (about 300 rows).
- No generated page in that bundle contains `](ref:`.
- The techwiki test files pass; `ruff check` passes on the changed files.

## Validation Commands
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_techwiki_naming.py packages/ai-parrot/tests/sdd/test_techwiki_bundle.py packages/ai-parrot/tests/sdd/test_techwiki_api.py packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`

## Completion Note
Implemented. `naming.UNLINK` sentinel (resolver may return a page name, `None` or `UNLINK`; anything else
raises `TypeError`); `rewrite_links` replaces an `UNLINK`ed link by its text. `BundleReport.unlinked` added
(informational, outside `ok()`). `assemble` skips the index page (`source is None and module is None`) and,
for a generated page, turns an unresolved `ref:` into `UNLINK` + an `unlinked` row; relative targets on
generated pages stay dangling. FEAT-818's test was renamed to
`test_unresolvable_links_in_a_generated_page_are_unlinked_or_dangling` with the new split; two tests added
(`test_reference_index_page_is_never_rewritten`, `test_unlinked_rows_reach_the_report_payload`) plus a naming
test. Tests: 82 passed in the four techwiki files; ruff clean. Strict full bundle from the branch: exit 0,
dangling 0, unlinked 300, collisions 0, no `](ref:` left in any page. Seat: native (main session).
