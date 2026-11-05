---
kind: brief
slug: techwiki-page-names-sidebar
key: 5baa3dae9606
base_branch: dev
source:
  type: text
  ref: "techwiki.yml release run 41962634580"
  url: https://github.com/phenobarbital/ai-parrot/actions/runs/41962634580
jira_issue_key: null
ledger_issue: null
created: '2026-11-05'
---

# Brief: Techwiki page names break the release publish; sidebar lists every API module

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/techwiki-page-names-sidebar/tasks/. -->

## Problem

Source (text, supplied by the owner on 2026-11-05):

> techwiki.yml release run 41962634580 failed: generated API page names contain a colon
> (`API-Reference-Reference:-<module>.md`, title `Reference: <module>` in parrot/sdd/techwiki/api.py:462);
> actions/upload-artifact rejects `:` so the publish job never ran and the GitHub wiki stays empty.

FEAT-801 (github-wiki-technical-reference, merged in PR #1982, released as 2.1.0) publishes the technical
reference to `ai-parrot.wiki.git` from `.github/workflows/techwiki.yml` on `release: published`. The 2.1.0
release run (event `release`, run 41962634580) built the bundle successfully:

```
{"skipped_modules": [], "adrs": 9, "authored": 285, "collisions": [], "commit": "3030a51…", "dangling": [],
 "generated": 3077, "release": "2.1.0"}
```

and then failed in `actions/upload-artifact@v4` (`.github/workflows/techwiki.yml:65`):

```
##[error]The path for one of the files in artifact is not valid:
/API-Reference-Reference:-ai_parrot_openlit_bridge.cli.md. Contains the following character:  Colon :
Invalid characters include:  Double quote ", Colon :, Less than <, Greater than >, Vertical bar |,
Asterisk *, Question mark ?, Carriage return \r, Line feed \n
```

The `publish` job `needs: bundle`, so it never ran. Every other run of the workflow is a `pull_request`
dry run (no push), and `workflow_dispatch` never publishes (`publish` is gated on
`github.event_name == 'release'`). `https://github.com/phenobarbital/ai-parrot/wiki` therefore still holds
only the initial commit of the wiki repository (`git ls-remote` → one ref, `master`).

## Root cause

1. `render_module` titles every generated page `Reference: <module>`
   (`packages/ai-parrot/src/parrot/sdd/techwiki/api.py:462`) under the section `API Reference`
   (`api.py:466`, hard-coded; `TechwikiConfig.reference_section` is ignored). `page_name` only rejects a
   literal hyphen and an empty title (`packages/ai-parrot/src/parrot/sdd/techwiki/naming.py:30-35`); it
   does not know the character set `actions/upload-artifact` refuses (`" : < > | * ? \r \n`). The resulting
   file is `API-Reference-Reference:-<module>.md`, which the artifact upload rejects. The spec itself baked
   the colon into the title (`sdd/specs/github-wiki-technical-reference.spec.md:307`), so this is a design
   gap, not an implementation slip.
2. The problem is not limited to generated pages. A local `parrot sdd techwiki bundle --release 2.1.0
   --strict` (3376 files) has 3104 names with forbidden characters: the 3078 generated pages plus 26
   authored pages whose H1 or frontmatter title carries a colon (for example
   `Server-&-APIs-Server-Layer:-BotManager-and-HTTP-Handlers.md`,
   `Clients-AbstractClient:-The-Provider-Client-Family.md`). Dropping the colon from the generated title
   alone would leave the release run failing on an authored page.
3. The bundle derives the `ref:<module>` id of a generated page by stripping the `Reference: ` prefix
   from its title (`packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py:166` and `bundle.py:259`), so
   the title format is load-bearing for link resolution and the manifest; `BundlePage` carries no module.
4. Separately observed in the same bundle: `_Sidebar.md` is 216 KB because `write_navigation` lists every
   generated module page under the reference section (`bundle.py:293-301`,
   `templates/sidebar.md.j2`). GitHub renders the sidebar on every wiki page, so a 3078-entry sidebar
   makes the published wiki unusable even once the publish succeeds.

## Research findings

- `wikitoolkit symbols blast page_name`: callers are `bundle._new_page` (authored + ADR pages),
  `bundle._generated_pages`, and the tests in `packages/ai-parrot/tests/sdd/test_techwiki_naming.py`
  (`TestPageName`, `test_page_name_never_contains_path_separators`) and
  `test_techwiki_bundle.py` (`test_reserved_page_name_is_a_collision`,
  `test_adr_title_with_hyphen_is_sanitized_not_fatal`).
- Tests that pin the current colon name and must change:
  `test_techwiki_bundle.py:200` (`[[API-Reference-Reference:-samplepkg.core]]`), `:231` (collision name),
  `:151` (`_Gen` stub with `title = "Reference: x.y"`).
- ADR titles are already sanitized (hyphen → space) by `_new_page(sanitize_title=True)`
  (`bundle.py:93`) because `docs/decisions/**` must not be edited; the same "name is derived, title is
  kept" principle applies to the forbidden characters.
- FEAT-801's own migration (TASK-5172) already rewrote authored titles via frontmatter to satisfy the
  hyphen rule (`wiki/integrations/migration/feat-202-ai-parrot-integrations.md:2` → `title: "Migration
  Guide: FEAT 202 — ai parrot integrations"`), confirming that titles are display text and names are
  derived.
- `_Sidebar.md` and every page link are validated by
  `test_every_rewritten_link_resolves_in_the_manifest` (every `[[Page]]` in every written `*.md` must be
  a manifest name or `Home`/`_Sidebar`), so a sidebar index page must be registered in the manifest.
- `wikitoolkit ledger context` on the three touched modules lists three open major issues that are
  NOT addressed here: `issue:0891861cb3c1` (generated ref links bypass bundle rewriting),
  `issue:b9829d5f3a2b` (missing configured roots pass strict coverage), `issue:5af0e518b2e8` (griffe
  static-only not enforced).
- `.github/workflows/techwiki.yml` needs no change: once no page name carries a forbidden character the
  upload succeeds and `publish` runs. Re-running run 41962634580 cannot pick this fix up (it checks out
  the 2.1.0 tag), so the wiki is first populated by the next published release or by a one-off manual
  push of a local bundle.

## Decisions

Answered by the owner in the Q&A round (2026-11-05):

1. **Sanitize, do not reject.** `page_name` replaces `" : < > | * ? \r \n` with a space (then collapses
   whitespace) in both section and title, so authored titles keep their colons and none of the 26 pages
   is edited. The hyphen rule is unchanged (still raised for authored pages, sanitized for ADRs).
2. **The sidebar fix is part of this brief** as a second task: the reference section of `_Sidebar.md`
   links one generated index page instead of every module page.
3. (Owner's original instruction) The generated page title becomes the bare module name
   (`parrot.memory.compaction` → `API-Reference-parrot.memory.compaction`), and the `ref:<module>` id is
   taken from a new `BundlePage.module` field instead of parsing the title.
4. (Research) `render_module` takes the section from `TechwikiConfig.reference_section` instead of the
   hard-coded `"API Reference"`; the default is unchanged.

## Fix plan

- **HOTFIX-5baa3dae9606-1** `techwiki-page-name-sanitization`: `naming.page_name` sanitizes the
  artifact-forbidden characters; `api.render_module` titles pages with the module name and the configured
  section; `BundlePage` gains `module`; `_manifest_entries`/`_ref_id` use it; tests updated and extended
  (every written bundle file name is artifact-safe); spec line 307 updated.
- **HOTFIX-5baa3dae9606-2** `techwiki-sidebar-reference-index` (depends on 1): `assemble` emits one
  generated index page `API-Reference` (name from `page_name(None, cfg.reference_section)`) listing every
  module page grouped by top-level package; `write_navigation` lists only that page under the reference
  section of `_Sidebar.md`; the index page is a manifest entry of kind `index`; tests.

## Validation commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_techwiki_naming.py packages/ai-parrot/tests/sdd/test_techwiki_bundle.py packages/ai-parrot/tests/sdd/test_techwiki_api.py packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`
- `parrot sdd techwiki bundle --out /tmp/techwiki-probe --release 2.1.0 --json --strict` followed by
  `ls /tmp/techwiki-probe | grep -E '[:"<>|*?]'` printing nothing, and `wc -c /tmp/techwiki-probe/_Sidebar.md`
  well under 10 KB.
