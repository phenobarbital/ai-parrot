---
type: feature
base_branch: dev
projects: [ai-parrot-tools, ai-parrot]
tags: [jira, oauth2-3lo, cli, knowledge-base, toolkit]
---

# Feature Specification: JiraToolkit upgrades — MCP parity, CLI 3LO auth, YAML knowledge base

**Feature ID**: FEAT-696
**Date**: 2026-10-16
**Author**: Jesus Lara (spec drafted by Claude)
**Status**: draft
**Target version**: next minor
**Source**: `sdd/proposals/jiratoolkit-upgrades.proposal.md` (accepted) · research `sdd/state/jiratoolkit-upgrades/`

---

## 1. Motivation & Business Requirements

### Problem Statement
Three related gaps in JiraToolkit (`parrot_tools/jiratoolkit.py`):

1. **Missing methods.** Compared with the Atlassian MCP surface, the toolkit lacks four operations:
   - linking two issues (`createIssueLink`);
   - create-field metadata for one issue type (`getJiraIssueTypeMetaWithFields`);
   - editing an existing comment (`addOrEditJiraIssueComment`, edit half);
   - cloud-id resolution as a tool (`getAccessibleAtlassianResources`).

   The other eight are covered [proposal F001]. Note that `jira_list_transitions` (L4242) returns status *history*
   from the changelog. The *workflow* transitions are returned by `jira_get_transitions` (L2841).
2. **No local 3LO login.** OAuth 2.0 (3LO) works only through `JiraOAuthManager`. That manager needs Redis and an
   aiohttp callback, and keys tokens per chat (channel, user) [F002]. A developer on a terminal has no way to
   authorize a personal Jira account.
3. **No site-structure cache.** Every call that needs issue types, components, priorities or custom-field ids
   queries Jira live [F004]. That structure barely changes and is known in advance.

### Goals
- G1: Add the four parity tools to JiraToolkit.
- G2: `parrot jiratoolkit auth` runs the 3LO flow with **manual paste** (no local server) and persists credentials:
  - client id, client secret and redirect URI go in `.env`;
  - the rotating tokens go in `~/.parrot/jira/settings.local.json` (mode 0600).
- G3: A new `auth_type="oauth2_local"` makes the toolkit use those stored tokens with transparent refresh, with no
  Redis and no PermissionContext.
- G4: A YAML knowledge base (KB) describing the site structure, loaded by the toolkit:
  - the toolkit uses the KB first and falls back to the live API (with a warning) on a miss;
  - `parrot jiratoolkit sync-kb` generates the structural sections and keeps the hand-curated ones.

### Non-Goals
- Replacing `JiraOAuthManager`, or changing the server-side Redis 3LO flow (it only gains extracted helpers).
- A loopback HTTP callback server. It was rejected in the proposal Q&A in favour of manual paste.
- Preserving YAML comments across `sync-kb` (see §7 Risks).
- Writing the KB into the wiki ledger. `status_map` is consumed as data only.

---

## 2. Architectural Design

### Overview
**M1 — Parity tools.** These are new `@tool_schema` methods on `JiraToolkit` that follow the existing pattern:
`asyncio.to_thread` over the `jira` 3.10.5 client, `requires_permission` on writes.

| Tool | Implementation | Notes |
|---|---|---|
| `jira_create_issue_link` | `JIRA.create_issue_link(type, inwardIssue, outwardIssue, comment)` | write |
| `jira_get_link_types` | `JIRA.issue_link_types()` | read |
| `jira_get_create_fields(project, issue_type)` | `JIRA.project_issue_fields(project, issue_type_id)` | read; resolves the issue-type name to an id through the KB first |
| `jira_edit_comment(issue, comment_id, body, template?, template_params?)` | `JIRA.comment(issue, id).update(body=…)` | write; reuses the FEAT-637 template machinery used by `jira_add_comment` |
| `jira_get_accessible_resources()` | 3LO / local: `fetch_accessible_resources(access_token)` | read; works in **every** auth mode |

How `jira_get_accessible_resources()` resolves the cloud id in static modes (basic/token/oauth1):
1. the KB's `cloud_id`/`site`, if a KB is loaded;
2. otherwise `GET <server_url>/_edge/tenant_info`. This endpoint is unauthenticated and undocumented, so the call
   is best-effort and a failure returns `{"cloud_id": None, "source": "unavailable"}`.

**M2 — 3LO helpers.** The token exchange, refresh, accessible-resources and `/myself` HTTP calls are extracted from
`JiraOAuthManager` private methods (L600-648 and `_refresh_tokens` L505) into module-level async functions in
`parrot/auth/jira_oauth.py`. These functions take an explicit `aiohttp.ClientSession`. `JiraOAuthManager` keeps
its behaviour and delegates to them. `JiraTokenSet` (L58) is reused unchanged as the persisted token shape.

**M3 — Local token store and resolver** (`parrot_tools/jira_local_auth.py`):
- `LocalJiraTokenStore` reads and writes `~/.parrot/jira/settings.local.json`. The path can be overridden with
  `JIRA_LOCAL_SETTINGS`. The file holds `{"version": 1, "default_site": str, "sites": {site_url: JiraTokenSet}}`.
  Writes are atomic (temp file + `os.replace`), use `chmod 0600`, and hold an `fcntl` lock.
- `FileTokenCredentialResolver(CredentialResolver)`:
  - `resolve()` ignores channel/user_id and returns the stored `JiraTokenSet` for the configured site;
  - if the token has expired, it takes the `fcntl` lock, **re-reads** the file, refreshes only if the token is
    still expired, keeps the old `refresh_token` when the response omits one, and writes back atomically (S7);
  - `get_auth_url()` raises `NotImplementedError`, so the toolkit's existing handler at L1287 yields
    `auth_url=None`;
  - it has the class attribute `single_user = True`.

**M4 — Toolkit wiring** for `auth_type="oauth2_local"`:
- In `__init__`, if no `credential_resolver` was passed, build `FileTokenCredentialResolver.from_env()`, then
  normalise to the existing 3LO path: set `self.auth_type = "oauth2_3lo"` and `self._local_single_user = True`.
  This way all 11 `oauth2_3lo` branches keep working untouched.
- `_pre_execute` (L1243): when `_local_single_user` is set, a missing PermissionContext or `user_id` no longer
  raises. The fixed user key `"local:cli"` is used instead.
- **Identity guard (S9):** if a PermissionContext *is* present, its `channel` must be in the resolver's
  `allowed_channels`, which defaults to `{"cli", "local"}` and can be overridden with
  `JIRA_LOCAL_ALLOWED_CHANNELS`. Any other channel raises `AuthorizationRequired`, so a developer's personal token
  is never used for an unrelated chat user.
- `jira_config.JiraToolkitConfig.auth_type` (L19) gains `"oauth2_local"` and a `knowledge_base: str | None` field.

**M5 — CLI** (`parrot_tools/jira_cli.py`, a click group named `jiratoolkit`, registered in
`parrot/cli/__init__.py` `_lazy_commands` beside `"manuals"`).

`auth [--site URL] [--scopes …] [--env-file PATH=.env] [--client-id] [--client-secret] [--redirect-uri]`:
1. Read `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET` and `JIRA_REDIRECT_URI` from flags, then env, then a prompt (the
   secret prompt is hidden).
2. Print the authorize URL, built from M2's `build_authorization_url` with a random `state`, `prompt=consent` and
   `DEFAULT_SCOPES`.
3. Read the pasted redirected URL or bare code. If a URL is pasted, its `state` must match, or the command aborts.
   A bare code skips the state check, with a printed warning. A pasted URL carrying `error=` (consent denied)
   aborts with that error (S6).
4. Exchange the code, then call accessible-resources. If more than one site is returned, the user picks one, or
   `--site` decides.
5. Call `/myself` and build a `JiraTokenSet`.
6. `LocalJiraTokenStore.save()`.
7. Upsert into `.env` (keys `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`, `JIRA_REDIRECT_URI`,
   `JIRA_AUTH_TYPE=oauth2_local`). Existing lines are replaced in place and the write is atomic.
8. Print the site, the account and the expiry.

Other subcommands:
- `status`: shows the site, account, expiry and scopes, and probes `/myself`. It never prints the secrets.
- `logout [--site]`: deletes the site entry, and the file once it is empty. It does not touch `.env`.
- `sync-kb [--output PATH] [--projects KEY,…]`: see M6.

**M6 — Knowledge base** (`parrot_tools/jira_kb.py`). This is the Pydantic model `JiraKnowledgeBase`, mirroring
the user-supplied schema (§2 Data Models) with `extra="allow"`.

Toolkit kwarg `knowledge_base: str | Path | JiraKnowledgeBase | None`, with env `JIRA_KB_PATH`. The KB is loaded
once in `__init__`. A missing or invalid file logs a warning and leaves the KB unset, which is never fatal.

KB lookups in the toolkit:

| Lookup | Effect |
|---|---|
| `resolve_issue_type(project, name_or_id)` | used by create and update calls and by `jira_get_create_fields` |
| `resolve_field(alias)` | e.g. `team` → `customfield_10001`, applied to `fields` keys in create/update |
| `priorities` | a priority missing from `scale` and `legacy` triggers the fallback; one in `legacy` logs a lint warning |
| `limits` | summary longer than `summary_max_chars`, or description longer than `description_max_chars`, raises `ValueError` before the API call |
| `templates` | when a FEAT-637 template is used, the issue type must be in `templates[t].types`; it defaults to `templates[t].default` |
| `status_map` | exposed through `JiraKnowledgeBase.status_category(status)` for callers; no toolkit behaviour depends on it |
| `components` | `jira_get_components` returns KB components when present |

`jira_get_issue_types` and `jira_get_projects` also serve from the KB when it covers the request.

**KB identity and drift (S4):** the KB is used only if its `site` (or `cloud_id`) matches the toolkit's
`server_url` (or the token's `cloud_id`). On a mismatch it is ignored and a warning is logged. When a KB-mapped
id is rejected by Jira (HTTP 400 naming the field), the toolkit re-resolves the id live once, retries, and logs
`jira KB stale`. The KB keeps no TTL; `verified` is informational.
KB parsing and resolution live entirely in `jira_kb.py` (S3); `jiratoolkit.py` only consumes resolved values.
Reads and writes stay in `JiraToolkit`, and `JiraInterface` remains untouched and read-only (S10).

**Fallback (decided):** on a KB miss, the toolkit queries the live API and logs
`WARNING jira KB stale: <what> not found in <path>`. The response carries `"source": "kb" | "live"`.

`sync-kb` behaviour (decided: CLI generates, human edits):
- It regenerates `site`, `cloud_id`, `verified` (today), `projects.*.issue_types`, `priorities.scale` (from
  `/priority`), `fields` entries discovered by name, and `components`.
- It **keeps** `status_map`, `templates`, `limits`, `priorities.legacy`, `priorities.default` and any custom keys
  from the existing file.
- It also keeps hand-edited `fields` aliases whose ids still exist.

### Component Diagram
```
parrot jiratoolkit ──(lazy)──→ parrot_tools.jira_cli
   auth/status/logout ──→ parrot.auth.jira_oauth helpers (exchange/refresh/resources/myself)
                      ──→ LocalJiraTokenStore (~/.parrot/jira/settings.local.json) + .env upsert
   sync-kb ──→ JiraToolkit (live reads) ──→ JiraKnowledgeBase.save(yaml)

JiraToolkit(auth_type=oauth2_local, knowledge_base=…)
   _pre_execute ──→ FileTokenCredentialResolver.resolve() ──refresh──→ jira_oauth helpers
   tools ──→ JiraKnowledgeBase (hit) | live jira.JIRA (miss + warning)
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `JiraToolkit.__init__` / `_pre_execute` | modifies | `oauth2_local` normalisation; single-user key |
| `CredentialResolver` (`parrot/auth/credentials.py:162`) | extends | `FileTokenCredentialResolver` |
| `JiraOAuthManager` | refactor (behaviour-preserving) | delegates to the new helpers |
| `JiraTokenSet` | reuses | persisted token shape |
| `parrot` click group `_lazy_commands` | registers | `"jiratoolkit"` |
| `JiraToolkitConfig` | modifies | `oauth2_local`, `knowledge_base` |

### Data Models
```python
class IssueTypeEntry(BaseModel):
    id: str
    subtask: bool = False
    level: int = 0

class ProjectEntry(BaseModel):
    name: str
    issue_types: dict[str, IssueTypeEntry] = {}

class PrioritiesEntry(BaseModel):
    scale: list[str] = []
    legacy: list[str] = []
    default: str | None = None

class LimitsEntry(BaseModel):
    description_max_chars: int | None = None
    summary_max_chars: int | None = None
    summary_target_chars: int | None = None

class TemplateEntry(BaseModel):
    types: list[str]
    default: str

class JiraKnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    site: str
    cloud_id: str | None = None
    verified: str | None = None            # ISO date string, kept as str to round-trip
    projects: dict[str, ProjectEntry] = {}
    priorities: PrioritiesEntry = PrioritiesEntry()
    status_map: dict[str, list[str]] = {}
    fields: dict[str, str] = {}            # alias -> Jira field id
    limits: LimitsEntry = LimitsEntry()
    templates: dict[str, TemplateEntry] = {}
    components: list[str] = []

class LocalSettings(BaseModel):            # ~/.parrot/jira/settings.local.json
    version: int = 1
    default_site: str | None = None
    sites: dict[str, JiraTokenSet] = {}
```

---

## 3. Module Breakdown

#### Delegation-eligible modules
| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 parity tools | yes | signatures below; `to_thread` + `wait_for(request_timeout+5)` like `jira_get_issue_types` L2956 | — |
| M2 oauth helpers | yes | pure functions below; manager delegates | — |
| M3 local store/resolver | yes | file layout, lock, 0600 fixed | — |
| M4 toolkit wiring | no | touches `_pre_execute` auth gate: needs care | security-sensitive branch |
| M5 CLI | yes | click group, steps fixed in §2 | — |
| M6 KB | yes | model + lookups + merge rules fixed in §2 | — |

### Module 1: Parity tools
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (modify)
- **Depends on**: M6 (`resolve_issue_type` in `jira_get_create_fields`). It falls back to a live lookup when there is
  no KB, so the hard dependency is only on the M6 model.
- **Interface Skeleton**:
  ```python
  class CreateIssueLinkInput(BaseModel):
      inward_issue: str; outward_issue: str; link_type: str = "Relates"; comment: Optional[str] = None
  class GetCreateFieldsInput(BaseModel):
      project: Optional[str] = None; issue_type: str
  class EditCommentInput(BaseModel):
      issue: str; comment_id: str; body: Optional[str] = None
      template: Optional[str] = None; template_params: Optional[Dict[str, Any]] = None

  @requires_permission("jira.write")
  @tool_schema(CreateIssueLinkInput)
  async def jira_create_issue_link(self, inward_issue: str, outward_issue: str,
                                   link_type: str = "Relates", comment: Optional[str] = None) -> Dict[str, Any]:
      """Link two issues (e.g. 'Blocks', 'Relates'). Use jira_get_link_types for valid names."""
  async def jira_get_link_types(self) -> List[Dict[str, Any]]:
      """List issue link types: name, inward and outward descriptions."""
  async def jira_get_create_fields(self, issue_type: str, project: Optional[str] = None) -> Dict[str, Any]:
      """Fields (id, name, required, schema, allowedValues) to create an issue of this type."""
  @requires_permission("jira.write")
  async def jira_edit_comment(self, issue: str, comment_id: str, body: Optional[str] = None,
                              template: Optional[str] = None,
                              template_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
      """Replace the body of an existing comment."""
  async def jira_get_accessible_resources(self) -> Dict[str, Any]:
      """Return {cloud_id, site_url, sites, source} in any auth mode."""
  ```

### Module 2: 3LO helpers
- **Path**: `packages/ai-parrot/src/parrot/auth/jira_oauth.py` (modify)
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  def build_authorization_url(client_id: str, redirect_uri: str, state: str,
                              scopes: Sequence[str] = DEFAULT_SCOPES) -> str: ...
  async def exchange_code(session: aiohttp.ClientSession, *, client_id: str, client_secret: str,
                          code: str, redirect_uri: str) -> Dict[str, Any]: ...
  async def refresh_access_token(session: aiohttp.ClientSession, *, client_id: str, client_secret: str,
                                 refresh_token: str) -> Dict[str, Any]: ...
  async def fetch_accessible_resources(session: aiohttp.ClientSession, access_token: str) -> List[Dict[str, Any]]: ...
  async def fetch_myself(session: aiohttp.ClientSession, access_token: str, cloud_id: str) -> Dict[str, Any]: ...
  # JiraOAuthManager._exchange_code/_fetch_accessible_resources/_fetch_myself → thin delegates (L600-648)
  ```

### Module 3: Local token store + resolver
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py` (new)
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  DEFAULT_SETTINGS_PATH = Path("~/.parrot/jira/settings.local.json")
  class LocalSettings(BaseModel): ...            # §2 Data Models
  class LocalJiraTokenStore:
      def __init__(self, path: Optional[Path] = None) -> None: """JIRA_LOCAL_SETTINGS overrides the default."""
      def load(self) -> LocalSettings: ...
      def get(self, site: Optional[str] = None) -> Optional[JiraTokenSet]: ...
      def save(self, token: JiraTokenSet, *, make_default: bool = True) -> None: """atomic, 0600, fcntl lock"""
      def delete(self, site: Optional[str] = None) -> bool: ...
  class FileTokenCredentialResolver(CredentialResolver):  # verified: parrot/auth/credentials.py:162
      single_user: ClassVar[bool] = True
      def __init__(self, store: LocalJiraTokenStore, client_id: str, client_secret: str,
                   site: Optional[str] = None) -> None: ...
      @classmethod
      def from_env(cls) -> "FileTokenCredentialResolver": """JIRA_CLIENT_ID/SECRET, JIRA_LOCAL_SITE"""
      async def resolve(self, channel: str, user_id: str) -> Optional[JiraTokenSet]: ...
      async def get_auth_url(self, channel: str, user_id: str) -> str: """raises NotImplementedError"""
  ```

### Module 4: Toolkit wiring (`oauth2_local`)
- **Path**: `jiratoolkit.py` (`__init__` near L980, `_pre_execute` L1243), `jira_config.py` L19
- **Depends on**: M3
- **Interface Skeleton**:
  ```python
  # JiraToolkit.__init__: new kwarg
  knowledge_base: Optional[Union[str, Path, "JiraKnowledgeBase"]] = None,
  # if self.auth_type == "oauth2_local": resolver = credential_resolver or FileTokenCredentialResolver.from_env();
  #   self.auth_type = "oauth2_3lo"; self._local_single_user = True
  # jira_config: auth_type: Literal["basic_auth", "token_auth", "oauth", "oauth2_local"] | None
  #              knowledge_base: str | None = None
  ```

### Module 5: CLI
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` (new) and `parrot/cli/__init__.py` (register)
- **Depends on**: M2, M3, M6
- **Interface Skeleton**:
  ```python
  @click.group(name="jiratoolkit")
  def cli() -> None: """Jira toolkit utilities."""
  @cli.command() ... def auth(site, scopes, env_file, client_id, client_secret, redirect_uri) -> None: ...
  @cli.command() def status(site) -> None: ...
  @cli.command() def logout(site) -> None: ...
  @cli.command(name="sync-kb") def sync_kb(output, projects) -> None: ...
  def parse_pasted_redirect(text: str) -> tuple[str, Optional[str]]: """(code, state|None)"""
  def upsert_env(path: Path, values: Mapping[str, str]) -> None: """replace-or-append, atomic"""
  ```

### Module 6: Knowledge base
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jira_kb.py` (new) + `jiratoolkit.py` lookups
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  class JiraKnowledgeBase(BaseModel):
      @classmethod
      def load(cls, path: Union[str, Path]) -> "JiraKnowledgeBase": ...
      def save(self, path: Union[str, Path]) -> None: ...
      def resolve_issue_type(self, project: str, name_or_id: str) -> Optional[IssueTypeEntry]: ...
      def resolve_field(self, alias: str) -> str: """alias → field id; unknown alias returned unchanged"""
      def status_category(self, status: str) -> Optional[str]: ...
      def merge_generated(self, generated: "JiraKnowledgeBase") -> "JiraKnowledgeBase":
          """Structural sections from `generated`; curated ones (status_map, templates, limits,
          priorities.legacy/default, extra keys) from self."""
  ```

---

## 4. Test Specification

### Unit Tests (`packages/ai-parrot-tools/tests/unit/`, `packages/ai-parrot/tests/` for M2)
| Test | Module | Description |
|---|---|---|
| `test_jira_parity_tools.py` | M1 | link/link-types/create-fields/edit-comment call the right `jira.JIRA` methods (mocked) |
| `test_accessible_resources_modes` | M1 | 3LO → helper; static+KB → KB; static, no KB → tenant_info; failure → `source: unavailable` |
| `test_jira_oauth_helpers.py` | M2 | the helpers post the right payloads (aiohttp mocked); the manager still passes the existing `test_jiratoolkit_oauth.py` |
| `test_jira_local_auth.py` | M3 | save → file mode 0600; atomic replace; refresh on expiry writes the rotated refresh token; `NotImplementedError` auth url |
| `test_oauth2_local_mode` | M4 | toolkit with `auth_type="oauth2_local"` runs a tool with no PermissionContext |
| `test_jira_cli.py` | M5 | `CliRunner`: state mismatch aborts; `error=` redirect aborts; bare code accepted with warning; `.env` upsert replaces in place; multi-site choice and invalid choice; `parrot jiratoolkit --help` resolves through the lazy group (S12) |
| `test_jira_parity_contract` | M1 | generated tool names, `jira.write` on link/edit, exact pycontribs call args, return shapes (S12) |
| `test_local_identity_guard` | M4 | `oauth2_local` + PermissionContext(channel="telegram") → `AuthorizationRequired`; `oauth2_3lo` without a context still raises |
| `test_kb_site_mismatch_and_drift` | M6 | KB for another site is ignored; a 400 on a mapped issue type triggers one live retry |
| `test_jira_kb.py` | M6 | loads the proposal's sample YAML; field alias; issue-type resolution; limits raise; KB miss → live + warning; `merge_generated` keeps curated sections |

### Test Data / Fixtures
- `tests/unit/fixtures/jira_kb_sample.yaml`: the user's example from the proposal §0, verbatim.
- `tmp_path`-based settings file; `monkeypatch` for `JIRA_LOCAL_SETTINGS` and `HOME`.

---

## 5. Acceptance Criteria
- [ ] AC1: The five M1 tools are registered and appear in `JiraToolkit().get_tools()`.
- [ ] AC2: `jira_get_accessible_resources` returns a result in basic, token, oauth1, oauth2_3lo and oauth2_local
  modes and never raises on a tenant_info failure.
- [ ] AC3: `parrot jiratoolkit auth` completes using only a pasted URL or code, with no listening socket.
  A `state` mismatch aborts with a non-zero exit.
- [ ] AC4: The client id, client secret and redirect URI land in `.env`. The tokens land **only** in
  `~/.parrot/jira/settings.local.json` (or `JIRA_LOCAL_SETTINGS`) with mode `0600`.
- [ ] AC5: With `JIRA_AUTH_TYPE=oauth2_local`, an expired access token is refreshed and the rotated refresh token is
  persisted before the call proceeds.
- [ ] AC6: `oauth2_3lo` behaviour is unchanged. Existing `test_jiratoolkit_oauth.py` and `JiraOAuthManager` tests
  pass.
- [ ] AC7: With a KB loaded, `jira_create_issue(issue_type="Story", project="NAV")` performs **no**
  issue-type/project lookup call. An unknown type triggers a live lookup and logs `jira KB stale`.
- [ ] AC8: Summary and description limits from the KB are enforced before any API call.
- [ ] AC9: `sync-kb` over an existing file keeps `status_map`, `templates`, `limits` and the priority
  `legacy`/`default` byte-for-value, and refreshes `verified`.
- [ ] AC10: A missing or invalid KB file never stops the toolkit from loading; it only logs a warning.
- [ ] AC10b: `oauth2_local` refuses a PermissionContext whose channel is not in `allowed_channels`.
- [ ] AC11: `ruff check` is clean; no new third-party dependency is added (PyYAML is already in core).

---

## 6. Codebase Contract
Verified against: `7b820a208` (dev, 2026-10-16).

### Verified Imports
```python
from parrot.auth.credentials import CredentialResolver          # verified: parrot/auth/credentials.py:162
from parrot.auth.jira_oauth import JiraTokenSet, DEFAULT_SCOPES, AUTHORIZATION_URL, TOKEN_URL, ACCESSIBLE_RESOURCES_URL  # jira_oauth.py:31-58
from parrot.auth.exceptions import AuthorizationRequired          # jiratoolkit.py:60
from .toolkit import AbstractToolkit                               # jiratoolkit.py:62
from .decorators import tool_schema, requires_permission          # jiratoolkit.py:63
from .jira_config import JiraToolkitConfig                         # jiratoolkit.py:64
import yaml                                                         # PyYAML>=6.0.2 in packages/ai-parrot/pyproject.toml:58
```

### Existing Class Signatures
```python
# parrot/auth/credentials.py
class CredentialResolver(ABC):                                            # L162
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]   # L166 (abstract)
    async def get_auth_url(self, channel: str, user_id: str) -> str        # abstract
    async def is_connected(self, channel: str, user_id: str) -> bool

# parrot/auth/jira_oauth.py
class JiraTokenSet(BaseModel):  # L58 — access_token, refresh_token, expires_at: float, cloud_id, site_url,
    # account_id, display_name, email?, scopes, granted_at, last_refreshed_at, available_sites
    is_expired: bool (property, 60s leeway); api_base_url: str (property)
class JiraOAuthManager:
    def __init__(self, client_id, client_secret, redirect_uri, *, app=None, redis_url=None,
                 redis_client=None, scopes=None, http_session=None)   # L98; raises without a redis source
    async def create_authorization_url(...)                            # L258
    async def handle_callback(self, code: str, state: str) -> Tuple[JiraTokenSet, Dict[str, Any]]  # L304
    async def _refresh_tokens(self, channel, user_id, token_set) -> JiraTokenSet  # L505 (Redis lock)
    async def _exchange_code(self, code: str) -> Dict[str, Any]                   # L600
    async def _fetch_accessible_resources(self, access_token: str) -> List[Dict]  # L619
    async def _fetch_myself(self, access_token: str, cloud_id: str) -> Dict       # L635

# parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):                                        # L742
    def __init__(self, server_url=None, auth_type=None, username=None, password=None, token=None,
                 oauth_consumer_key=None, oauth_key_cert=None, oauth_access_token=None,
                 oauth_access_token_secret=None, default_project=None, credential_resolver: Any = None,
                 workflow_paths=None, verify_credentials: bool = True, templates_dir=None,
                 templates: Optional[Mapping[str, str]] = None, **kwargs)  # L844-862
    # auth_type resolved from arg or JIRA_AUTH_TYPE (L886); oauth2_3lo requires credential_resolver (L982-984)
    async def _pre_execute(...)        # L1243-1320: raises AuthorizationRequired without _permission_context/user_id;
                                       # calls credential_resolver.resolve(channel, user_id); get_auth_url NotImplementedError tolerated (L1287)
    def _init_jira_client_from_token(self, token_set: Any) -> JIRA         # L1224 — uses token_set.api_base_url/access_token
    async def jira_get_transitions(self, issue: str, expand: Optional[str] = None)  # L2841 (workflow transitions)
    async def jira_add_comment(self, issue, body=None, is_internal=False, file_ids=None,
                               template=None, template_params=None)        # L2856
    async def jira_get_issue_types(self, project: Optional[str] = None)    # L2956
    async def jira_get_projects(self) -> Dict[str, Any]                    # L3142
    async def jira_get_components(self, project: Optional[str] = None)     # L3215
    async def jira_list_transitions(self, issue: str)                      # L4242 — status HISTORY, not workflow

# jira 3.10.5
JIRA.create_issue_link(type, inwardIssue, outwardIssue, comment=None)
JIRA.issue_link_types(force=False) -> list[IssueLinkType]
JIRA.comment(issue, comment, expand=None) -> Comment   # Comment.update(body=...)
JIRA.project_issue_types(project, startAt=0, maxResults=50)
JIRA.project_issue_fields(project, issue_type, startAt=0, maxResults=50)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FileTokenCredentialResolver` | `JiraToolkit._pre_execute` | `resolve(channel, user_id)` | `jiratoolkit.py:1279` |
| M2 helpers | `JiraOAuthManager` private methods | delegation | `jira_oauth.py:600-648` |
| `jira_cli` | `parrot` group | `_lazy_commands["jiratoolkit"]` | `parrot/cli/__init__.py:109-135` |
| `JiraKnowledgeBase` | `JiraToolkit.__init__` | `knowledge_base=` / `JIRA_KB_PATH` | `jiratoolkit.py:860` |

### Does NOT Exist (Anti-Hallucination)
- ~~`JiraToolkit.jira_create_issue_link` / `jira_edit_comment` / `jira_get_create_fields` / `jira_get_accessible_resources`~~
- ~~a non-Redis token store for Jira 3LO~~ (all 3LO tokens live in Redis today)
- ~~`parrot jira …` / `parrot jiratoolkit …` CLI~~
- ~~`python-dotenv` as a declared dependency~~: do not `import dotenv`; write `upsert_env` by hand.
- ~~`ruamel.yaml`~~: not a dependency; use PyYAML.
- ~~`JIRA_OAUTH_CLIENT_ID`~~ as the canonical env name: the codebase mostly uses `JIRA_CLIENT_ID`,
  `JIRA_CLIENT_SECRET` and `JIRA_REDIRECT_URI`.

### Edit Sites (Blueprint Anchors)
Verified against: `7b820a208`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `class ConfigureClientInput(BaseModel):` (new input models before it) | L732 | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `        templates: Optional[Mapping[str, str]] = None,` (new kwarg) | L860 | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `        if self.auth_type != "oauth2_3lo":` (`_pre_execute`) | L1251 | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `    async def jira_get_issue_types(self, project: Optional[str] = None) -> List[Dict[str, Any]]:` | L2956 | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `    async def jira_list_transitions(self, issue: str) -> List[Dict[str, Any]]:` (new tools near here) | L4242 | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jira_config.py` | MODIFY | `    auth_type: Literal["basic_auth", "token_auth", "oauth"] \| None = None` | L19 | 1 |
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | `    async def _exchange_code(self, code: str) -> Dict[str, Any]:` | L600 | 1 |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `    "manuals": "parrot_tools.procedures.cli",` | L127 | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/jira_kb.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Blocking `jira` calls go through `asyncio.to_thread` + `asyncio.wait_for(timeout=self.request_timeout + 5)` (as
  at L2956).
- Writes are decorated `@requires_permission("jira.write")` and `@tool_schema(...)`, in that order (L2854-2855).
- Use aiohttp only. HTTP in the CLI goes through the M2 helpers with an owned `ClientSession`.
- CLI subcommands follow `parrot_tools/procedures/cli.py`: click, lazily imported, `asyncio.run` per command.

### Known Risks / Gotchas
- **Rotating refresh tokens.** Atlassian invalidates the old refresh token on use, so two processes refreshing at
  once lock one of them out. Mitigation: the `fcntl` lock is held across read → refresh → write; after taking the
  lock, re-read the file and skip the refresh if another process already rotated the token.
- **The token file holds a long-lived refresh token.** Use mode 0600 and create the parent dir 0700. Never log it,
  and `status` masks it.
- **`.env` upsert** must not reorder or drop unrelated lines, and must quote values that contain `#` or spaces.
- **`_edge/tenant_info`** is undocumented. It is best-effort only and must not break the tool.
- **PyYAML drops comments**, so `sync-kb` loses the user's inline comments. Mitigation: write a header noting that
  the file is generated and that the curated sections are preserved; document this.
- **`jiratoolkit.py` churn** (FEAT-637/639/688 all touch it): `/sdd-task` must re-verify anchors.
- **The single-user bypass** in `_pre_execute` must be reachable **only** through `oauth2_local`. A server deploy
  using `oauth2_3lo` must still require a PermissionContext. Cover this with a test.

### External Dependencies
None new. `jira` 3.10.5, PyYAML ≥ 6.0.2, aiohttp and click are already present.

---

## 8. Open Questions
- [x] Token store → *Resolved in proposal*: both. Client id and secret go in `.env`; the rotating tokens go in
  `settings.local.json`.
- [x] KB source → *Resolved in proposal*: the CLI generates it and a human edits it; curated sections are kept on
  re-sync.
- [x] KB miss → *Resolved in proposal*: fall back to the live API and log a warning.
- [x] settings.local.json location → *Resolved in proposal*: per user, `~/.parrot/jira/settings.local.json`, mode
  0600.
- [x] Cloud-id tool modes → *Resolved in proposal*: all modes (KB, then `_edge/tenant_info`, in static modes).
- [x] Redirect handling → *Resolved in proposal*: manual paste of the redirected URL or code; no local server.
- [ ] Which channel names do the local entry points (`parrot agent` REPL, agentd) set on PermissionContext? The
  `allowed_channels` default `{"cli", "local"}` must match them; verify during M4. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: completed · Transcript: `sdd/state/FEAT-696/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Expose oauth2_3lo in JiraToolkitConfig (api) | REJECT | `jira_config.py` deliberately limits auth types to the static modes (comment at L17-18): 3LO needs a server-injected resolver. Only `oauth2_local` is added | — |
| S2 | Explicit `knowledge_base` constructor contract (api) | CONFIRM | already designed | §2 M6, §3 M4 |
| S3 | KB parsing outside the toolkit module (architecture) | CONFIRM | `jira_kb.py` owns parsing and resolution | §2 M6 |
| S4 | Present KB entries may be stale (risk) | CONFIRM | site/cloud_id identity check + one live retry on rejection | §2 M6, §4 |
| S5 | Split OAuth protocol from the Redis manager (architecture) | CONFIRM (partial) | stateless helpers extracted; pluggable stores for the manager are out of scope | §2 M2 |
| S6 | Site selection and denial as first-class results (api) | CONFIRM | multi-site prompt, `error=` abort, tests | §2 M5, §4 |
| S7 | Cross-process refresh locking (risk) | CONFIRM | lock → re-read → refresh → keep old refresh_token if omitted | §2 M3 |
| S8 | Canonical env names; `.env` git-ignored (risk) | CONFIRM | `JIRA_CLIENT_ID`/`JIRA_CLIENT_SECRET`/`JIRA_REDIRECT_URI` (`parrot/conf.py:727-729`); `.env` verified git-ignored | §2 M5, §6 |
| S9 | Local resolver identity (architecture) | CONFIRM | `allowed_channels` guard; exact channel names left open | §2 M4, §8 |
| S10 | Keep JiraInterface read-only (architecture) | CONFIRM | all new tools live in JiraToolkit | §2 M6 |
| S11 | `_edge/tenant_info` must not be authoritative (api) | REJECT (partial) | the user decided on all-modes support; the KB is preferred and the response carries `source`, so tenant_info stays best-effort | §2 M1 |
| S12 | Contract tests for parity tools and CLI lazy load (testing) | CONFIRM | added test rows | §4 |

Summary: **10** confirmed · **2** rejected · **0** escalated (S9's channel names are recorded as §8 Q7).

---

## Worktree Strategy
- **Isolation**: one feature worktree `feat-FEAT-696-jiratoolkit-upgrades`; each task gets a sub-worktree.
- **Module graph**:
  - M3 → M2 (uses the helpers).
  - M4 → M3 (builds `FileTokenCredentialResolver`).
  - M5 → M2, M3, M6.
  - M1 → M6 (KB lookup in `jira_get_create_fields` and `jira_get_accessible_resources`).
  - M2 and M6 are roots and can run concurrently.
- **Shared files**: `jiratoolkit.py` is touched by M1, M4 and the M6 lookups, so those tasks are serialized on it.
- **Exclusive resources**: none (no lockfile or dependency changes).
- **Cross-feature**: rebase-check against any open FEAT-637/639/688 work on `jiratoolkit.py`.

---

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-16 | Claude (for Jesus Lara) | Initial draft from accepted proposal |
