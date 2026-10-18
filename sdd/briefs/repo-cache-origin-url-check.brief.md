---
kind: brief
slug: repo-cache-origin-url-check
key: cs-228
base_branch: main
source:
  type: code-scanning
  ref: cs:228
  url: https://github.com/phenobarbital/ai-parrot/security/code-scanning/228
jira_issue_key: null
ledger_issue: null
created: '2026-10-18'
---

# Brief: Parse the clone origin URL before matching its host in `RepoWikiCache._origin_matches`

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/repo-cache-origin-url-check/tasks/. -->

## Problem

GitHub code-scanning alert #228 (CodeQL `py/incomplete-url-substring-sanitization`,
severity `warning`, security severity **high**, CWE-020, state `open`, first seen
2026-10-15 on `main` @ `95cec61c`):

> The string `github.com/` may be at an arbitrary position in the sanitized URL.
>
> — `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py:304` (cols 14-41)

Rule help: "treating the URL as a string and checking if one of the allowed hosts
is a substring of the URL is very prone to errors. Malicious URLs can bypass such
security checks by embedding one of the allowed hosts in an unexpected location.
[...] Parse a URL before performing a check on its host value."

`RepoWikiCache._clone_matches()` is the guard that decides whether an on-disk
clone under the wiki cache really belongs to the canonical `owner/name`
repository before the cache `git pull`s it and builds a wiki plane from it. It
reads `git remote get-url origin` from the clone and hands it to
`_origin_matches()`. That helper accepts any origin string that merely
*contains* `github.com/` somewhere, so a clone whose remote is
`https://evil.example/github.com/owner/name` or
`https://github.com.evil.example/x/github.com/owner/name` passes identity
validation, and the cache then pulls from and indexes that remote as if it were
`owner/name`.

## Root cause

`RepoWikiCache._origin_matches` (`packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py:296-306`)
normalises the origin as an opaque string instead of parsing it:

```python
        if normalized.startswith("git@github.com:"):
            normalized = normalized.partition(":")[2]
        elif "github.com/" in normalized:                      # repo_cache.py:304  <- alert
            normalized = normalized.split("github.com/", 1)[1]
        return normalized.lower() == repository
```

Line 304 is a substring test, and line 305 keeps everything *after the first*
`github.com/`, so the host that is actually contacted is never checked. Any URL
of the form `<anything>github.com/<owner>/<name>` matches, including ones whose
real host is attacker-controlled. The SCP-style `git@github.com:` branch
(line 302) is an exact prefix check and is not affected.

Verified anchors (`test -e` + `sed -n`):

- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py:304` —
  `        elif "github.com/" in normalized:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py:281` — the only
  caller: `if origin is None or not self._origin_matches(origin, paths.repository):`

The file is byte-identical on `origin/main`, `origin/dev` and the local checkout,
so the fix applies cleanly to `main` and syncs down.

## Research findings

- **Symbols**: `RepoWikiCache._origin_matches` (staticmethod, repo_cache.py:296-306);
  sole caller `RepoWikiCache._clone_matches` (repo_cache.py:273-291), itself
  called twice from `RepoWikiCache._ensure_clone` (repo_cache.py:245, :260).
  `wiki_blast_radius` on the symbol: empty (private staticmethod; no transitive
  dependents outside the module).
- **What legitimate origins look like**: the cache always clones through
  `GitToolkit.clone_repo(..., prefer_gh=False, private=True)`
  (repo_cache.py:250-258). With `prefer_gh=False` the toolkit builds the URL via
  `GitToolkit._clone_url(slug, False)` → `https://github.com/<owner>/<name>.git`
  (`packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1429-1434`, :1580)
  and passes the token through the subprocess environment (`_auth_env`), so the
  persisted `origin` never carries userinfo. `RepoCachePaths.repository` is
  already a validated, lower-cased bare `owner/name` slug (`paths_for`,
  repo_cache.py:133-174), never a URL.
- **Prior art for the correct shape**: `GitToolkit._display_slug`
  (gittoolkit.py:1409-1419) already does it right — `urlparse()` then
  `parsed.hostname in ("github.com", "www.github.com")` then strips the path.
  The fix mirrors that allowlist.
- **Existing tests**: `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py`
  has a `FakeGit` double whose `_run_subprocess` answers `remote get-url origin`
  with `git.origin` (test_repo_cache.py:49-51), and
  `test_ensure_clone_validates_origin_and_branch` (test_repo_cache.py:197-207)
  already proves a *different* GitHub repo is discarded. No test exercises
  `_origin_matches` directly, and none covers a look-alike host.
- **Ledger**: `wikitoolkit ledger context` on repo_cache.py reports no open
  issues.
- **Practical exposure**: the origin string comes from the cache's own clone
  directory, so exploitation needs write access to the cache tree (a colliding
  or tampered clone). The guard exists precisely for that case, so it must
  check the real host. Fixing it also closes the open CodeQL alert on `main`.

## Assumptions

(Autonomous run — no interview could be held; unresolved decisions recorded here.)

1. **Key**: no Jira key or ledger id exists, so the brief key is the alert
   identifier `cs-228` (ref-safe spelling of `cs:228`) rather than a repeat of
   the slug, giving the branch `hotfix-cs-228-repo-cache-origin-url-check`.
2. **Parse, don't substring**: rewrite `_origin_matches` to `urllib.parse.urlparse`
   any URL-form origin and require `parsed.hostname in {"github.com", "www.github.com"}`
   and `parsed.scheme in {"https", "http", "ssh", "git"}`; take the repository
   path only from `parsed.path`. Keep the exact-prefix `git@github.com:`
   SCP-style branch as is (it is not substring-based). Anything else returns
   `False`.
3. **Host allowlist is exact**, not suffix-based: the cache only ever clones
   `github.com`, and `_display_slug` uses the same two-host allowlist. No
   GitHub Enterprise hosts are admitted (none are configured anywhere today).
4. **No behaviour change for legitimate origins**: `https://github.com/o/n.git`,
   `https://github.com/o/n`, trailing `/`, mixed case, `ssh://git@github.com/o/n.git`,
   `git@github.com:o/n.git` and a userinfo-bearing
   `https://x-access-token:...@github.com/o/n.git` all still match.
5. **Single task**: one file plus its test module; no `--split`.

## Fix plan

- **HOTFIX-cs-228-1** — Replace the substring check in
  `RepoWikiCache._origin_matches` with host-parsed matching (module-level
  `_GITHUB_HOSTS` / `_ORIGIN_SCHEMES` allowlists, `urlparse`), and add
  `_origin_matches` unit tests (accepted and bypass-attempt URLs) plus an
  `_ensure_clone` behavioural test proving a look-alike-host clone is discarded
  and re-cloned, in `test_repo_cache.py`.

## Validation commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py -q`
