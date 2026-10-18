---
kind: brief
slug: crew-google-credential-guards
key: 97d065c34ef4
base_branch: dev
source:
  type: ledger
  ref: issue:97d065c34ef4
  url: null
jira_issue_key: null
ledger_issue: issue:97d065c34ef4
created: '2026-10-18'
---

# Brief: Crew-level default Google client injection must honor all four credential signals

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/crew-google-credential-guards/tasks/. -->

## Problem

Ledger issue `issue:97d065c34ef4` (bug, major, discovered from spec:FEAT-575 code
review, 2026-09-19):

> AgentCrew.__init__'s default-Google-orchestration-client injection (crew.py
> ~line 235-239) only guards with `"api_key" not in kwargs` before adding
> `api_key=google_api_key`. Unlike the per-agent path (apply_google_api_key,
> credentials.py, which also checks credentials_file/credentials/vertexai), a
> caller doing `AgentCrew(llm='google', credentials_file=..., google_api_key=X)`
> would get api_key=X injected alongside credentials_file, contradicting
> docs/crew_handler.md's Precedence section which lists all four as credential
> signals that should win.

A caller who brings their own Google credential (`credentials_file`,
`credentials`, or `vertexai=True`) to the crew's **orchestration** client still
gets `api_key=google_api_key` injected next to it, so the crew-level key can
silently override or conflict with the explicit credential — behavior the docs
promise cannot happen.

## Root cause

`AgentCrew.__init__` has two inline default-Google-client injection sites whose
guard tests only the presence of `api_key`:

- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:238` — string-LLM
  branch: `if google_api_key and llm.lower() in GOOGLE_PROVIDER_KEYS and "api_key" not in kwargs:`
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:246` — default-Google
  branch (llm is None/other): `if google_api_key and "api_key" not in kwargs:`

The canonical per-agent injector `apply_google_api_key`
(`packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py:122-132`) refuses
injection when any of `_CREDENTIAL_KWARGS = ("api_key", "credentials_file",
"credentials")` is truthy (`credentials.py:129`) or `vertexai` is truthy
(`credentials.py:131`). The `__init__` sites were written literally from the
FEAT-575 spec's Module 2 interface skeleton and never gained the other three
signals — a spec-literal gap, ruled a real bug by the /sdd-fix triage of
2026-10-18 ("crew.py __init__ lines 238/246 missing
credentials_file/credentials/vertexai guards — real bug").

Documented contract being violated: `docs/crew_handler.md:581-591`
("### Precedence — An explicit credential always wins: `llm_kwargs.api_key`,
`llm_kwargs.credentials_file`, `llm_kwargs.credentials`, a truthy
`llm_kwargs.vertexai`, passing an `AbstractClient` instance as `llm`").

## Research findings

- Symbols: `AgentCrew.__init__` (crew.py:158-320); `apply_google_api_key`
  (credentials.py:102-135); `_CREDENTIAL_KWARGS` (credentials.py:27, private);
  `GOOGLE_PROVIDER_KEYS` (credentials.py:24, already imported by crew.py:61).
- Blast radius of `AgentCrew.__init__` via `wiki_blast_radius`: empty
  (constructor; no tracked transitive dependents). The guard tightening only
  narrows when injection happens, so callers passing no explicit credential are
  unaffected.
- The other two `self._google_api_key` consumers — crew.py:2153-2154 (run_loop
  fallback) and crew.py:4407-4408 (executive-summary fallback) — build clients
  with **no caller kwargs**, so no competing credential signal exists there;
  they are out of scope, matching the ledger triage's "focused fix in crew.py
  __init__".
- Existing tests: `packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py`
  (TASK-3453) covers the __init__ sites but has no `credentials_file` /
  `credentials` / `vertexai` cases; `test_crew_from_definition_google_key.py`
  (TASK-3454) covers the per-agent path.
- Related ledger context on the two files: only this issue.

## Assumptions

(No interview was needed — research and the prior /sdd-fix triage settled every
decision; recorded here per the --no-interview convention.)

1. **Fix the code, not the docs.** The issue offered "tighten the check" vs
   "scope the docs Precedence section to per-agent injection only". The
   2026-10-18 /sdd-fix triage already ruled it a real code bug to fix in
   crew.py, and the docs' Precedence list is the intended contract.
2. **Match `apply_google_api_key` semantics exactly**: refuse injection when any
   of `api_key` / `credentials_file` / `credentials` is **truthy** or `vertexai`
   is truthy — not mere key presence. This makes the crew-level guard identical
   to the per-agent one (an explicit `api_key=None` no longer blocks injection;
   that is the canonical, documented semantics).
3. **Share the signal list**: expose a helper
   `has_explicit_google_credential(kwargs: Mapping[str, Any]) -> bool` from
   `parrot/bots/flows/crew/credentials.py` (built on `_CREDENTIAL_KWARGS` +
   `vertexai`), use it from both `__init__` sites and from
   `apply_google_api_key`, instead of duplicating the four-key list in crew.py.
4. The crew.py:2153 / crew.py:4407 fallback sites stay untouched (no kwargs
   flow there).

## Fix plan

- **HOTFIX-97d065c34ef4-1** — Add `has_explicit_google_credential()` to
  `credentials.py`, refactor `apply_google_api_key` to use it, tighten both
  `AgentCrew.__init__` guards (crew.py:238, crew.py:246) to use it, and extend
  `test_crew_google_key.py` with credentials_file / credentials / vertexai /
  explicit-None cases for both branches.

## Validation commands

- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_from_definition_google_key.py -q`
- `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/crew.py packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py`
