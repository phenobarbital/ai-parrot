---
kind: brief
slug: techwiki-markdown-links
key: 1f9d9ff0ec07
base_branch: dev
source:
  type: text
  ref: "GitHub wiki after the manual 2.1.0 publish: sidebar error, index timeout, Home without links"
  url: https://github.com/phenobarbital/ai-parrot/wiki
jira_issue_key: null
ledger_issue: null
created: '2026-11-05'
---

# Brief: Techwiki must emit Markdown links, not `[[wiki links]]`

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/techwiki-markdown-links/tasks/. -->

## Problem

Source (owner report, 2026-11-05, after brief 5baa3dae9606 and the manual push of the 2.1.0 bundle to
`ai-parrot.wiki.git`, wiki commit 44e15e2):

> Ya cargó el wiki, pero en realidad allí no hay nada: hay un HOME con títulos (categorías) que dicen
> abajo "13 page(s)", pero sin hipervínculos ni más nada, una sidebar en idénticas condiciones y solo
> las API references están como hyperlinks pero dice "The Wiki page took too long to render, please edit
> to render faster".

Observed in the HTML GitHub serves (fetched with curl on 2026-11-05):

- The custom sidebar box (`<div class="wiki-custom-sidebar">`) on every page contains only
  `Sorry, there was an error rendering this page.` — `_Sidebar.md` (18 KB, 295 `[[Page]]` links) fails
  to render.
- `API-Reference` (164 KB, 3078 `[[Page]]` links) returns 504 on cold render and then carries the
  banner "The Wiki page took too long to render".
- `Home.md` renders but has no links: the template writes one `## Section` heading and `N page(s)` per
  section and nothing else.
- An authored page with two `[[Page]]` links in its body renders them as anchors, so the syntax itself
  works; it is the volume per document that breaks.

## Root cause

GitHub resolves every `[[Page Name]]` wiki link against the wiki's page list at render time. With
3374 pages that lookup is expensive, and a document carrying hundreds or thousands of such links either
errors (sidebar) or times out (index). FEAT-801 chose the `[[Page Name]]` form for every generated link:

- `rewrite_links` turns a resolved relative `.md` or `ref:` link into `[[<page>]]`
  (`packages/ai-parrot/src/parrot/sdd/techwiki/naming.py:108`), discarding the author's link text in
  the process (the rendered anchor shows the raw page name, e.g.
  `Architecture-AI-Parrot-—-Exposure,-Interoperability-&-Hardening-Architecture`). Its fragment branch
  already emits a plain `[text](page#fragment)` link (`naming.py:106`).
- `templates/sidebar.md.j2:2` emits `- [[{{ page.name }}]]` per page.
- `_reference_index_page` emits `- [[{page.name}]]` per module
  (`packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py:187`).
- `templates/home.md.j2:8` lists sections with a page count only; Home was specified as a landing page
  with counts, so it has no links by design.

Verified by experiment on the live wiki (commits 8e1d0e5 and 6fd28de of `ai-parrot.wiki.git`): the same
`_Sidebar.md` and `API-Reference.md` rewritten to `[text](Percent-Encoded-Page-Name)` render correctly —
sidebar with its anchors, index in 4 s with 4249 anchors and no banner.

## Research findings

- `wikitoolkit symbols blast rewrite_links`: callers are `bundle.assemble` (authored and ADR pages only;
  generated pages are skipped at `bundle.py:270-272`, which is the open ledger issue
  `issue:0891861cb3c1`) and the tests in `test_techwiki_naming.py` (`TestRewriteLinks`,
  `test_rewrite_links_skips_external_urls`, `test_rewrite_links_resolves_fragment_links_and_flags_missing`,
  `test_rewrite_links_leaves_fenced_code_untouched`).
- Tests pinning the `[[...]]` form: `test_techwiki_naming.py:72,81,93,128`;
  `test_techwiki_bundle.py:69,95,201,258-260,265`; and
  `test_every_rewritten_link_resolves_in_the_manifest` (`test_techwiki_bundle.py:233-247`) scans
  `[[Page]]` tokens to prove every link resolves to a manifest name.
- GitHub's own page list links percent-encode the page name (`%E2%80%94` for `—`, `%2C` for `,`,
  `%26` for `&`) and resolve a `+` in a name as `-` or `%2B` alike, so `urllib.parse.quote(name,
  safe="-._~")` is a safe href.
- `wikitoolkit ledger context` on `naming.py` / `bundle.py`: open issues `issue:0891861cb3c1`
  (generated `ref:` links bypass rewriting), `issue:b9829d5f3a2b`, `issue:5af0e518b2e8` — none is fixed
  here; the first is directly related (generated pages still carry literal `(ref:module)` links) and
  stays open.
- `.github/workflows/techwiki.yml` needs no change.

## Decisions

Confirmed by the owner on 2026-11-05 ("Sí, ábrelo e implementa el fix") after the diagnosis above:

1. Every link the bundler emits is a standard Markdown link `[text](href)` with `href =
   urllib.parse.quote(page_name, safe="-._~")`, never `[[Page Name]]`. This supersedes the
   `[[Page Name]]` wording of FEAT-801 (`sdd/specs/github-wiki-technical-reference.spec.md:264`, `:593`).
2. `rewrite_links` keeps the author's link text.
3. Link text in navigation is the page title (`BundlePage.title`), not the page name; the reference
   index uses the module name.
4. Home lists the same links as the sidebar under each section (every authored and decision page; for
   the reference section the single index link) and keeps the page count.

## Fix plan

- **HOTFIX-1f9d9ff0ec07-1** `techwiki-markdown-links`: add `page_href` / `page_link` to `naming.py`;
  `rewrite_links`, the sidebar and home templates and `_reference_index_page` emit Markdown links;
  `write_navigation` passes `title` + `href` rows to both templates; tests updated (including the
  manifest-resolution scan); spec wording updated.

## Validation commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_techwiki_naming.py packages/ai-parrot/tests/sdd/test_techwiki_bundle.py packages/ai-parrot/tests/sdd/test_techwiki_api.py packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`
- `parrot sdd techwiki bundle --out /tmp/techwiki-probe --release 2.1.0 --json --strict`, then
  `grep -c '\[\[' /tmp/techwiki-probe/_Sidebar.md /tmp/techwiki-probe/Home.md /tmp/techwiki-probe/API-Reference.md`
  printing `0` for each.
