# HOTFIX-1f9d9ff0ec07-1: Emit Markdown links instead of `[[wiki links]]` in the techwiki bundle

**Feature**: techwiki-markdown-links (BRIEF-1f9d9ff0ec07)
**Spec**: sdd/briefs/techwiki-markdown-links.brief.md
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
GitHub fails to render `_Sidebar.md` ("error rendering this page") and times out on `API-Reference.md`
because each `[[Page Name]]` link is resolved against the 3374-page wiki at render time; `Home.md` has no
links at all. Plain `[text](Percent-Encoded-Name)` links render fine (verified on the live wiki). See the
brief's Root cause and Decisions.

## Scope
- `naming.py`: add `page_href(name: str) -> str` returning `urllib.parse.quote(name, safe="-._~")` and
  `page_link(name: str, text: str) -> str` returning `f"[{text}]({page_href(name)})"`. In `rewrite_links`,
  a resolved target becomes `page_link(page, <original link text>)`; a resolved target with a fragment
  becomes `[text](page_href(page)#fragment)`. Never emit `[[...]]`. Update the docstrings.
- `bundle.py`:
  - `_reference_index_page` lists `- {page_link(page.name, str(page.module))}` per module.
  - `write_navigation` builds `home_rows` and `sidebar_rows` whose `pages` entries are dicts
    `{"title": page.title, "href": page_href(page.name)}` (keep the reference-section filter from
    HOTFIX-5baa3dae9606-2 for BOTH Home and the sidebar) and adds `"count": len(items)` (the unfiltered
    count) to each row.
- Templates: `sidebar.md.j2` renders `- [{{ page.title }}]({{ page.href }})`; `home.md.j2` keeps the
  release/commit/site header and, per section, the `## <name>` heading, the `<count> page(s)` line and the
  same link list as the sidebar.
- Tests:
  - `test_techwiki_naming.py`: the four pinned expectations become Markdown links, e.g.
    `[Memory](memory.md)` → `[Memory](Memory)`, `[Compaction](ref:parrot.memory.compaction)` →
    `[Compaction](Reference-parrot.memory.compaction)`; add a test that a page name with `—`, `,`, `&` and
    a space-derived hyphen yields a percent-encoded href (`page_href("A-—-B,-C-&-D")` ==
    `"A-%E2%80%94-B%2C-C-%26-D"`) and that `rewrite_links` keeps the author's text.
  - `test_techwiki_bundle.py`: update `[[Decisions-Decision-One]]`, `[[Beta-Two]]`,
    `[[API-Reference-samplepkg.core]]`, the sidebar/index assertions of
    `test_sidebar_links_one_reference_index_page_instead_of_every_module` to the Markdown form; rewrite
    `test_every_rewritten_link_resolves_in_the_manifest` to collect every Markdown link target without a
    URL scheme from every written `*.md`, strip any `#fragment`, `urllib.parse.unquote` it, and assert it
    is a manifest name (or `Home`); add a test that `Home.md` links every authored and decision page and
    the single `API-Reference` link, and that no written file contains `[[`.
- Spec: change the two `[[Page Name]]` / `[[Name]]` mentions at
  `sdd/specs/github-wiki-technical-reference.spec.md:264` and `:593` to `[text](Page-Name)` with a short
  "(brief 1f9d9ff0ec07: GitHub cannot render hundreds of wiki links per page)" note.

**NOT in scope**: rewriting `ref:` links inside generated pages (`issue:0891861cb3c1`); `techwiki.yml`;
splitting the index page; any authored page under `wiki/`.

## Files to Create / Modify
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/naming.py`
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py`
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/templates/sidebar.md.j2`
- MODIFY `packages/ai-parrot/src/parrot/sdd/techwiki/templates/home.md.j2`
- MODIFY `packages/ai-parrot/tests/sdd/test_techwiki_naming.py`
- MODIFY `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py`
- MODIFY `sdd/specs/github-wiki-technical-reference.spec.md`

## Codebase Contract
- Verified: `naming.py:84` `def rewrite_links(text: str, resolver: Callable[[str], str | None]) -> str`;
  `naming.py:106` fragment branch `return f"[{match.group(1)}]({page}#{fragment})"`; `naming.py:108`
  `return f"[[{page}]]"`.
- Verified: `bundle.py:187` `lines.extend(f"- [[{page.name}]]" ...)` in `_reference_index_page`.
- Verified: `bundle.py:322` `def write_navigation(pages, report, cfg, out)`; it builds `home_rows` and
  `sidebar_rows` (reference-section filter on `module is None`) and renders `home.md.j2` / `sidebar.md.j2`.
- Verified: `templates/sidebar.md.j2:2` `{% for page in section.pages %}- [[{{ page.name }}]]`;
  `templates/home.md.j2:8-10` `## {{ section.name }}` + `{{ section.pages|length }} page(s)`.
- Verified: `BundlePage` fields `source, section, title, name, body, module`.
- Verified: test pins at `test_techwiki_naming.py:72,81,93,128` and
  `test_techwiki_bundle.py:69,95,201,258-260,265`; manifest scan at `test_techwiki_bundle.py:233-247`.
- Does NOT exist: `page_href`, `page_link`, a `href`/`count` key in the navigation rows.

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/naming.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/templates/sidebar.md.j2", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/templates/home.md.j2", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_naming.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_bundle.py", "action": "MODIFY"},
    {"path": "sdd/specs/github-wiki-technical-reference.spec.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/naming.py#rewrite_links",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#_reference_index_page",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#write_navigation"
  ]
}
```

## Acceptance Criteria
- No file written by `write_bundle` contains `[[`.
- `_Sidebar.md`, `Home.md` and `API-Reference.md` link every page with `[title](percent-encoded-name)`;
  every such target, unquoted, is a manifest name.
- Rewritten authored links keep the author's text.
- The techwiki test files pass; `ruff check` passes on the changed files.

## Validation Commands
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_techwiki_naming.py packages/ai-parrot/tests/sdd/test_techwiki_bundle.py packages/ai-parrot/tests/sdd/test_techwiki_api.py packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`

## Completion Note
(pending)
