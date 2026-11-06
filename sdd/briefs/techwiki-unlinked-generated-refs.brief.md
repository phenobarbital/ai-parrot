---
kind: brief
slug: techwiki-unlinked-generated-refs
key: 93f079cc8e3f
base_branch: dev
source:
  type: text
  ref: "techwiki.yml run 42064651073 (PR #1993, FEAT-818) — strict bundle exits 1 with 301 dangling links; merged into dev"
  url: https://github.com/phenobarbital/ai-parrot/actions/runs/42064651073/job/127375316679
jira_issue_key: null
ledger_issue: null
created: '2026-11-05'
---

# Brief: A generated page's `ref:` to a module without a page is unlinked, not dangling

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/techwiki-unlinked-generated-refs/tasks/. -->

## Problem

Owner report (2026-11-05): "el CI de techwiki falló otra vez" — run 42064651073, the `pull_request` dry run
of PR #1993 (FEAT-818 / TASK-5232, "rewrite and validate links in generated API pages"). The PR was merged
into `dev` (c4554b373b) with that run red. Reproduced on `dev` with
`python -m parrot.sdd.scripts.techwiki_bundle --root . --out … --release dev --json --strict`: exit 1,
`dangling` has 301 rows, every other counter is clean (3077 generated, 285 authored, 9 ADRs, 0 collisions).

| Origin | Rows | Example |
|---|---|---|
| generated module pages, target `ref:<module>` | 300 | `{"source": "ref:parrot.bots.agent", "target": "ref:parrot.mcp"}` |
| the `API-Reference` index page | 1 | `{"source": "index:API-Reference", "target": "API-Reference-parrot.loaders.splitters.md"}` |

Most frequent targets: `ref:parrot_tools.abstract` (82), `ref:parrot_tools.toolkit` (39),
`ref:parrot_tools.decorators` (27), `ref:parrot.forms` (20), `ref:parrot.auth` (16), `ref:parrot` (13),
`ref:parrot.memory.dream` (12), `ref:parrot.manager` (8).

Until this is fixed every `release: published` run fails in `bundle --strict` before `publish`, so the
GitHub wiki is not refreshed by releases (the same outcome brief 5baa3dae9606 fixed for a different cause).

## Root cause

FEAT-818 removed the `if page.source is None: continue` guard in `assemble`
(`packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py:280-306`) so generated pages are link-rewritten
and validated too. Two cases it did not anticipate in the real repository:

1. **Re-exports from modules that have no page.** `module.md.j2` renders every alias as
   ``Re-exported from [`pkg.mod.Name`](ref:pkg.mod)``. `render_module` returns `None` for a module with
   no public members, so no page exists for it. `packages/ai-parrot-tools/src/parrot_tools/abstract.py`,
   `toolkit.py` and `decorators.py` are two-to-six-line import shims without `__all__` (griffe does not
   treat a bare import as public); `packages/ai-parrot/src/parrot/forms/__init__.py` is the documented
   compatibility shim to `parrot_formdesigner`. The `resolve` closure records every such target as
   dangling (`bundle.py:303`), and `--strict` fails. The fixture package used by
   `test_generated_page_ref_links_are_rewritten` only re-exports from a module that does have a page.
2. **The reference index page is rewritten too.** `_reference_index_page` (brief 5baa3dae9606) is a
   `source=None, module=None` page whose links are already final hrefs. A module literally named
   `parrot.loaders.splitters.md` yields the target `API-Reference-parrot.loaders.splitters.md`; the
   generated-page branch of `resolve` treats a target ending in `.md` as an unresolvable relative path
   (`bundle.py:294-298`) and reports it dangling.

## Research findings

- `wikitoolkit symbols blast rewrite_links` / `assemble`: callers are `techwiki_bundle.main`,
  `techwiki.check` and the bundle tests; `rewrite_links`'s resolver protocol is
  `Callable[[str], str | None]` (`packages/ai-parrot/src/parrot/sdd/techwiki/naming.py:115`), with
  `None` meaning "leave the link untouched" (`naming.py:136`). There is no "drop the link" outcome.
- FEAT-818's own test `test_unresolvable_links_in_a_generated_page_are_dangling`
  (`packages/ai-parrot/tests/sdd/test_techwiki_bundle.py:335`) asserts that both `ref:samplepkg.gone`
  and `../other.md` from a generated page are dangling. The relative half (AC-3 of TASK-5232: never
  dereference `page.source` on a generated page) stays valid; the `ref:` half is the behaviour this brief
  changes.
- `BundleReport` is a dataclass serialised with `asdict` in `report_payload` (`bundle.py:36-49`);
  `ok()` is `not collisions and not dangling`, so a new informational list does not affect the gate.
- `parrot.auth` declares `__all__` and still has no page. That is a separate generator gap (griffe and
  a dynamic `__all__`), not addressed here; it only makes the unlink rule fire where a page could exist.

## Decisions

Confirmed by the owner on 2026-11-05 ("Sí, ábrelo e implementa el fix"):

1. On a generated page, a `ref:<module>` whose module has no page is **unlinked**: the link is replaced
   by its own text (the code-formatted qualified name) and the row goes to a new informational
   `BundleReport.unlinked` list, which never fails `--strict`.
2. Relative targets on generated pages stay dangling (FEAT-818 AC-3 unchanged).
3. The reference index page (`source is None and module is None`) is never link-rewritten: its hrefs
   are final.
4. Authored and ADR pages keep today's semantics: an unresolved `ref:` or relative link is dangling.

## Fix plan

- **HOTFIX-93f079cc8e3f-1** `techwiki-unlinked-generated-refs`: `naming.UNLINK` sentinel honoured by
  `rewrite_links`; `BundleReport.unlinked`; `assemble` skips the index page and returns `UNLINK` for an
  unresolved generated `ref:`; tests updated and added.

## Validation commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_techwiki_naming.py packages/ai-parrot/tests/sdd/test_techwiki_bundle.py packages/ai-parrot/tests/sdd/test_techwiki_api.py packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`
- `parrot sdd techwiki bundle --out /tmp/techwiki-probe --release dev --json --strict` exits 0 with
  `"dangling": []`.
