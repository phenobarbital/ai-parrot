# TASK-2402: Refactor `JiraToolkit` read methods to delegate to `JiraInterface`

**Feature**: FEAT-454 — Jira Ticket Extractor → LLM Wiki (`issues` namespace)
**Spec**: `sdd/specs/jira-extractor-llmwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2400
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** (spec §3 M2, G1). Without this task the feature still
works — but G1 is false, because there would be **two** Jira read
implementations in the repo, guaranteed to drift. This task makes
`JiraInterface` the single one.

**This is a behaviour-preserving refactor with a zero-tolerance regression
gate.** `jiratoolkit.py` is 3511 lines and contested by three other in-flight
efforts (FEAT-138/TASK-948 envelope flip, TASK-953 error hardening, and the
3LO spec). The spec is explicit (§7): the existing test suites *"must pass
**unchanged** (not adjusted to fit the refactor)"*. If a test needs editing to
go green, the refactor is wrong — not the test.

Public tool signatures and the `JiraToolEnvelope` shape must not change
(FEAT-138/TASK-948).

---

## Scope

- Give `JiraToolkit` a lazily-constructed `JiraInterface` built from the
  toolkit's already-resolved auth attributes (no second credential
  resolution, no second `_cfg` pass).
- Route these **read** paths through it, deleting the now-duplicated transport
  code from the toolkit:
  - `jira_get_issue` (`:1358`)
  - `jira_search_issues` (`:2638`)
  - `jira_count_issues` (`:2896`)
  - `jira_get_projects` (`:2254`)
  - `jira_verify_auth` (`:2310`)
  - `_get_full_changelog` (`:1314`)
  - `_issue_to_dict` (`:1134`) — reimplement as a thin projection over
    `JiraInterface.parse_issue`, **only if** the resulting dict is
    byte-compatible; see the constraint below.
- Keep **in the toolkit, untouched**: the `JiraToolEnvelope` construction,
  `_pre_execute` permission/3LO wiring, `_apply_structured_output`,
  `_ensure_bounded_jql`, `_extract_field_history`, error hardening, dataframe
  storage, and every write method.
- Run the full pre-existing Jira test suite as the gate.

**NOT in scope**:
- Any change to a public tool signature, docstring-derived tool description,
  or the envelope shape. A diff in any of those fails this task.
- Any Jira **write** path (transition, comment, assign, create, attachment).
- `_ensure_bounded_jql` — stays in the toolkit; `JiraInterface` deliberately
  does not have it.
- Touching `parrot/knowledge/wiki/` — that is TASK-2401/2403/2404.
- "Improving" anything you notice while in here. This file is contested;
  an unrelated change is a merge conflict for three other efforts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | Read methods delegate to `JiraInterface` |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | Ensure `ai-parrot` core dep covers `parrot.interfaces.jira` (verify first — may need no change) |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py` | CREATE | Delegation-specific tests (the *new* ones) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-24 at commit
> `53df566ef`. Confirm each anchor before writing code.

### Verified Imports

```python
# New, from TASK-2400 (core — already a dependency of ai-parrot-tools):
from parrot.interfaces.jira import JiraInterface, JiraAuthError, JiraDependencyError
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (3511 lines)
class JiraToolEnvelope(TypedDict, total=False): ...          # :58  — DO NOT CHANGE
class JiraAuthenticationError(RuntimeError): ...             # :78
class StructuredOutputOptions(BaseModel): ...                # :132
class JiraToolkit(AbstractToolkit): ...                      # :660
    def __init__(self, server_url=None, auth_type=None, username=None,
        password=None, token=None, oauth_consumer_key=None,
        oauth_key_cert=None, oauth_access_token=None,
        oauth_access_token_secret=None, default_project=None,
        credential_resolver=None, workflow_paths=None,
        verify_credentials=True, **kwargs): ...              # :731  — SIGNATURE FROZEN
    def _init_jira_client(self) -> JIRA: ...                 # :955
    def _init_jira_client_from_token(self, token_set) -> JIRA: ...  # :1017
    def _issue_to_dict(self, issue_obj: Any) -> Dict[str, Any]: ... # :1134
    def _ensure_bounded_jql(self, jql: Optional[str]) -> str: ...   # :1198  KEEP
    def _apply_structured_output(...)                        # :1254  KEEP
    def _extract_field_history(self, changelog_entries, field_name): ...  # :1291  KEEP
    async def _get_full_changelog(self, issue: str, page_size: int = 100)  # :1314
    async def jira_get_issue(...)                            # :1358
    async def jira_get_issue_types(self, project=None) -> List[Dict[str, Any]]  # :2084
    async def jira_get_projects(self) -> Dict[str, Any]: ... # :2254
    async def jira_verify_auth(self) -> Dict[str, Any]: ...  # :2310
    async def jira_search_issues(self, jql: str, start_at: int = 0,
        max_results: Optional[int] = 100, fields: Optional[str] = None,
        expand: Optional[str] = None, json_result: bool = True,
        store_as_dataframe: bool = False, dataframe_name: Optional[str] = None,
        summary_only: bool = False,
        structured: Optional[StructuredOutputOptions] = None,
    ) -> JiraToolEnvelope: ...                               # :2638  SIGNATURE FROZEN
    async def jira_count_issues(self, jql: str,
        group_by: Optional[List[str]] = None) -> Dict[str, Any]: ...  # :2896

# :751-760  — _cfg(key, default): navconfig first, then os.getenv
# :767-775  — the no-heuristic auth rule (already mirrored in JiraInterface)
# :2152-2154 — _SERAPH_HEADER / _SERAPH_FAIL_VALUES
# :2174-2176 — api_path is auth-dependent (v3 for oauth2_3lo, else v2)
# :2259-2266 — an empty search result MUST be probed, never trusted
# :1029     — _CLIENT_CACHE_MAX_SIZE = 100
# :1030-1033 — _OAUTH_SCOPES (includes write:jira-work — the TOOLKIT needs
#              write scope; JiraInterface deliberately does not. Do NOT let
#              the interface's read-only scopes narrow the toolkit's.)
```

### The regression gate — these suites must pass UNCHANGED

```
packages/ai-parrot-tools/tests/test_jiratoolkit_envelope.py
packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py
packages/ai-parrot-tools/tests/unit/test_jiratoolkit_verify_credentials.py
packages/ai-parrot/tests/test_jiratoolkit_defaults.py
packages/ai-parrot/tests/test_jiratoolkit_permissions.py
packages/ai-parrot/tests/test_jira_extraction_refactor.py
packages/ai-parrot/tests/test_jira_history_logic.py
packages/ai-parrot/tests/test_jira_optimization.py
packages/ai-parrot/tests/test_jira_callbacks.py
packages/ai-parrot/tests/test_jira_comment_attachments.py
packages/ai-parrot/tests/test_jira_assignment.py
packages/ai-parrot/tests/test_jira_transition_dispatch.py
packages/ai-parrot/tests/test_jira_transition_to.py
```
Capture a **baseline** before touching anything (see Agent Instructions step 3)
— some of these may already be failing or skipping for unrelated reasons, and
you must not be blamed for, or hide behind, a pre-existing failure.

### Does NOT Exist

- ~~A `JiraInterface` that can build the toolkit's envelope~~ — the envelope
  is a `parrot_tools` concern (`jiratoolkit.py:58`). `JiraInterface` returns
  raw dicts and `JiraIssue` models. The toolkit wraps them, exactly as it
  wraps its own results today.
- ~~`JiraInterface._ensure_bounded_jql`~~ — deliberately not ported
  (TASK-2400 scope note). The toolkit keeps calling its own.
- ~~`JiraInterface` write methods~~ — none exist. Every write path in the
  toolkit keeps using `self.jira` directly.
- ~~A change to `JiraToolkit.__init__`'s signature~~ — frozen. `JiraInterface`
  is constructed from already-resolved attributes *inside* the toolkit; no new
  constructor parameter.
- ~~`self.jira` being removable~~ — the write paths and
  `_init_jira_client_from_token` still need it. Keep it.

---

## Implementation Notes

### Pattern to Follow — the delegation seam

Construct the interface lazily from resolved state, never re-resolving config:

```python
    @property
    def _read_interface(self) -> "JiraInterface":
        """Shared Jira read implementation (FEAT-454, G1).

        Built once from this toolkit's already-resolved auth attributes so
        there is exactly one credential resolution per toolkit instance.
        """
        if self.__read_interface is None:
            from parrot.interfaces.jira import JiraInterface
            self.__read_interface = JiraInterface(
                server_url=self.server_url,
                auth_type=self.auth_type,
                username=self.username,
                password=self.password,
                token=self.token,
                oauth_consumer_key=self.oauth_consumer_key,
                oauth_key_cert=self.oauth_key_cert,
                oauth_access_token=self.oauth_access_token,
                oauth_access_token_secret=self.oauth_access_token_secret,
                credential_resolver=self.credential_resolver,
                request_timeout=self.request_timeout,
                verify_credentials=False,   # the toolkit already verified
            )
        return self.__read_interface
```

Verify every attribute name above against the real `__init__` (`:731-950`)
before writing this — the list is from the constructor signature, but the
*stored attribute* names may differ.

**3LO is the hard case.** In `oauth2_3lo` mode the toolkit resolves a
per-user client in `_pre_execute` (`:1040+`) and caches it. The interface must
be handed that already-resolved client rather than resolving the token a
second time (which would double the token round-trips and could diverge on
which user is current). Read `_pre_execute` in full and add whatever
seam `JiraInterface` needs — e.g. an `attach_client(client)` method — rather
than duplicating the resolution.

### Key Constraints

- **`_issue_to_dict` byte-compatibility.** Read `:1134` in full and diff its
  output against `parse_issue` + a projection. If they are not byte-compatible
  (very likely — the toolkit's dict is LLM-shaped and includes fields
  `JiraIssue` does not model), **leave `_issue_to_dict` alone**. Reimplementing
  it is optional; the mandatory part is that the *transport* (fetch/search/
  changelog/projects/verify) goes through `JiraInterface`. Record the decision
  in the Completion Note.
- **Envelope shape is byte-compatible or the task fails.** Add a test that
  snapshots `sorted(JiraToolEnvelope.__annotations__)` and one that snapshots
  the key set of a real envelope built from a fake client.
- **Error taxonomy must not change.** The toolkit raises
  `JiraAuthenticationError` / `AuthorizationRequired`; `JiraInterface` raises
  `JiraAuthError`. Translate at the seam so callers and the existing
  error-hardening tests see exactly what they saw before.
- **Do not narrow OAuth scopes.** The toolkit needs `write:jira-work`
  (`:1030-1033`); the interface requests read-only. The toolkit's scopes must
  win in the toolkit's own 3LO path.
- **Do not change `verify=False`** in the static-mode client options
  (`:960`) — TASK-2400 keeps parity with an overridable kwarg; the toolkit
  must keep the old default.
- Async-first, `self.logger`, no `print`, Google-style docstrings.
- **Keep the diff small and append-shaped.** `jiratoolkit.py` is contested; a
  reformatting pass or an import reshuffle turns this into a merge conflict
  for three other efforts.

### Known Gotchas

- `jira_count_issues` (`:2896`) may use `maxResults=0` and read `total`, a
  distinct call shape from `jira_search_issues`. Confirm before routing it
  through the paginating iterator — counting should **not** page through every
  issue. If `JiraInterface` lacks a `count_issues`, add one there (a small
  addition to TASK-2400's module is in scope for *this* task) rather than
  making the toolkit page.
- `jira_search_issues` takes `start_at`/`max_results` (a single page), while
  `JiraInterface.search_issues` is an exhaustive async iterator. Do **not**
  change the tool's paging semantics: use the interface's single-page
  primitive, or add one. The tool must still return one page.
- `store_as_dataframe` / `dataframe_name` / `summary_only` /
  `structured` all post-process the raw result **inside the toolkit**. They
  stay there.
- `jira_verify_auth` (`:2310`) does a *raw* GET so the
  `X-Seraph-Loginreason` header is inspectable. `JiraInterface.verify_auth`
  must expose the header (or a parsed verdict), not swallow it.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` — the whole file;
  read `:660-1060` and `:2150-2960` before editing
- `packages/ai-parrot/src/parrot/interfaces/jira/client.py` — TASK-2400's output
- `packages/ai-parrot/src/parrot/interfaces/obsidian/` +
  `packages/ai-parrot-tools/src/parrot_tools/obsidian.py` — the *finished*
  shared-interface/toolkit split this task reproduces for Jira. Read the
  Obsidian toolkit to see how thin a delegating skin should be.

---

## Acceptance Criteria

- [ ] **G1**: the read methods contain no direct `jira`/REST transport —
      `jira_get_issue`, `jira_search_issues`, `jira_count_issues`,
      `jira_get_projects`, `jira_verify_auth` and `_get_full_changelog` all
      reach Jira via `JiraInterface`.
- [ ] **G1**: every pre-existing test in the gate list above passes, with a
      diff of **zero lines** in those test files
      (`git diff --stat -- '*test_jira*'` is empty).
- [ ] `JiraToolkit.__init__`'s signature is byte-identical to before
      (`git diff` shows no change to `:731`'s parameter list).
- [ ] `JiraToolEnvelope.__annotations__` is unchanged, and an envelope built
      from a fake client has the same key set as before the refactor.
- [ ] Every write method still works and still uses `self.jira`.
- [ ] The error taxonomy is unchanged: an auth failure still surfaces as
      `JiraAuthenticationError` / `AuthorizationRequired`, not `JiraAuthError`.
- [ ] All four auth modes still resolve, including `oauth2_3lo`, and 3LO
      resolves the per-user token **exactly once** per call.
- [ ] `jira_search_issues` still returns a single page honouring
      `start_at`/`max_results` — paging semantics unchanged.
- [ ] `jira_count_issues` does not page through the whole result set.
- [ ] New tests pass: `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py -v`
- [ ] Full gate passes: `pytest packages/ai-parrot-tools/tests packages/ai-parrot/tests -k jira -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py
"""FEAT-454 M2 — the toolkit delegates reads; nothing else moves."""
import inspect

import pytest

from parrot_tools.jiratoolkit import JiraToolEnvelope, JiraToolkit


# Snapshot taken BEFORE the refactor. Regenerate ONLY if FEAT-138/TASK-948
# intentionally changes the envelope — never to make this test pass.
ENVELOPE_KEYS_BASELINE: set[str] = set()   # fill from the pre-refactor run

INIT_PARAMS_BASELINE: tuple[str, ...] = (
    "self", "server_url", "auth_type", "username", "password", "token",
    "oauth_consumer_key", "oauth_key_cert", "oauth_access_token",
    "oauth_access_token_secret", "default_project", "credential_resolver",
    "workflow_paths", "verify_credentials", "kwargs",
)


class TestFrozenPublicSurface:
    def test_init_signature_unchanged(self):
        params = tuple(inspect.signature(JiraToolkit.__init__).parameters)
        assert params == INIT_PARAMS_BASELINE

    def test_envelope_annotations_unchanged(self):
        assert set(JiraToolEnvelope.__annotations__) == ENVELOPE_KEYS_BASELINE

    @pytest.mark.parametrize("method,expected", [
        ("jira_search_issues", ("self", "jql", "start_at", "max_results",
                                "fields", "expand", "json_result",
                                "store_as_dataframe", "dataframe_name",
                                "summary_only", "structured")),
        ("jira_count_issues", ("self", "jql", "group_by")),
    ])
    def test_tool_signatures_unchanged(self, method, expected):
        params = tuple(inspect.signature(getattr(JiraToolkit, method)).parameters)
        assert params == expected


class TestDelegation:
    def test_read_methods_have_no_direct_transport(self):
        """G1: no read method builds its own JIRA client or raw request."""
        for name in ("jira_get_issue", "jira_search_issues",
                     "jira_count_issues", "jira_get_projects",
                     "_get_full_changelog"):
            src = inspect.getsource(getattr(JiraToolkit, name))
            for banned in ("_init_jira_client(", "JIRA(", "requests.",
                           "self.jira._session"):
                assert banned not in src, f"{name} still does {banned}"

    def test_read_methods_reach_the_interface(self, monkeypatch):
        """Each read path must touch _read_interface exactly once."""
        # Build a toolkit with a stubbed interface and assert the call lands.
        ...

    def test_interface_built_once_per_toolkit(self):
        """No second credential resolution (G1)."""
        ...

    def test_write_methods_still_use_self_jira(self):
        for name in ("jira_transition_issue", "jira_add_comment",
                     "jira_create_issue"):
            method = getattr(JiraToolkit, name, None)
            if method is None:
                continue
            assert "self.jira" in inspect.getsource(method)


class TestErrorTaxonomyPreserved:
    def test_interface_auth_error_is_translated(self):
        """A JiraAuthError from the interface must NOT leak to callers."""
        from parrot.interfaces.jira import JiraAuthError
        from parrot_tools.jiratoolkit import JiraAuthenticationError
        # Inject an interface that raises JiraAuthError; assert the toolkit
        # surfaces JiraAuthenticationError / AuthorizationRequired instead.
        ...

    def test_missing_jira_dependency_message_is_actionable(self):
        ...


class TestOAuth3LO:
    def test_toolkit_scopes_not_narrowed_by_interface(self):
        """The toolkit needs write scope (jiratoolkit.py:1030-1033)."""
        assert "write:jira-work" in JiraToolkit._OAUTH_SCOPES

    def test_per_user_token_resolved_once_per_call(self):
        """The interface must reuse the toolkit's resolved client, not
        resolve the token a second time."""
        ...


class TestCountDoesNotPage:
    def test_count_issues_does_not_iterate_every_page(self):
        """A 50k-issue JQL must not be paged through just to count it."""
        ...
```

> The `...` bodies are deliberate: fill them against the real code, and drive
> each one from a fake `JiraInterface` / fake `JIRA` rather than the network.
> The **frozen-surface** tests above are the ones that must be complete and
> exact — they are this task's real gate, alongside the untouched pre-existing
> suites.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-extractor-llmwiki.spec.md` (§3 M2, §7 "Known Risks" — the `jiratoolkit.py` is contested paragraph, G1) for full context
2. **Check dependencies** — TASK-2400 must be in `sdd/tasks/completed/`
3. **Capture the baseline BEFORE editing anything**:
   ```bash
   source .venv/bin/activate
   pytest packages/ai-parrot-tools/tests packages/ai-parrot/tests -k jira \
     -q > artifacts/logs/feat454-jira-baseline.txt 2>&1 || true
   python -c "from parrot_tools.jiratoolkit import JiraToolEnvelope as E; \
     print(sorted(E.__annotations__))"
   ```
   Paste the envelope key set into `ENVELOPE_KEYS_BASELINE` and the pass/fail
   counts into the Completion Note. Pre-existing failures are recorded, not
   fixed, and not hidden behind.
4. **Verify the Codebase Contract** — read `jiratoolkit.py:660-1060` and
   `:2150-2960` in full. Read `_pre_execute` and the 3LO client cache before
   designing the seam. Read `parrot_tools/obsidian.py` for how thin a
   delegating toolkit should be.
5. **Update status** in `sdd/tasks/index/jira-extractor-llmwiki.json` → `"in-progress"`
6. **Implement** one read method at a time, running the gate after each. Keep
   the diff append-shaped; do not reformat, reorder imports, or fix unrelated
   nits in this file.
7. **Verify** all acceptance criteria are met — in particular
   `git diff --stat -- '*test_jira*'` must be empty.
8. **Run an adversarial second-opinion review** on the diff (project
   convention, `CLAUDE.md` "Adversarial Second Opinion"): give the reviewer
   only the diff, the requirement "this must be behaviour-preserving", and the
   question. Mark each finding CONFIRM / REJECT / ESCALATE.
9. **Move this file** to `sdd/tasks/completed/TASK-2402-jiratoolkit-delegation-refactor.md`
10. **Update index** → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Baseline vs. post-refactor test counts**: (required)
**`_issue_to_dict` decision**: reimplemented over `parse_issue` | left alone (and why)
**Adversarial review findings**: CONFIRM / REJECT / ESCALATE per finding

**Deviations from spec**: none | describe if any
