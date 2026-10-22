---
id: F007
query_id: Q007
type: read
intent: Read JiraToolkit constructor / config surface (where a templates dir would be configured).
executed_at: 2026-10-07T22:55:00Z
duration_ms: 3000
parent_id: null
depth: 0
---

# F007 — Constructor: _cfg() precedence, JIRA_DEFAULT_* and workflow_paths precedents

## Summary

`__init__` (L698) resolves every setting through a local `_cfg(key, default)` helper (navconfig → env var). It already loads `JIRA_DEFAULT_PROJECT/ISSUE_TYPE/LABELS/COMPONENTS/DUE_DATE_OFFSET/ESTIMATE` and a two-tier `workflow_paths` map (`JIRA_WORKFLOW_PATH` default + `JIRA_WORKFLOW_PATH_<PROJECT>` per-project env + programmatic kwarg override, keyed by upper-cased project with a `_DEFAULT` sentinel). That per-project-override pattern is the obvious model for per-project / per-issuetype template selection. The Agent Studio surface is a separate `JiraToolkitConfig` Pydantic model (`jira_config.py`, `extra="forbid"`) exposing only server_url/auth_type/username/password/token/default_project/verify_credentials.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 698-716
  symbol: `JiraToolkit.__init__`
  excerpt: |
    def __init__(self, server_url=None, auth_type=None, username=None, password=None, token=None,
                 oauth_consumer_key=None, oauth_key_cert=None, oauth_access_token=None,
                 oauth_access_token_secret=None, default_project=None, credential_resolver=None,
                 workflow_paths: Optional[Dict[str, Union[str, List[str]]]] = None,
                 verify_credentials: bool = True, **kwargs):
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 718-723
  symbol: `_cfg`
  excerpt: |
    def _cfg(key: str, default: Optional[str] = None) -> Optional[str]:
        if (nav_config is not None) and hasattr(nav_config, "get"):
            val = nav_config.get(key)
            if val is not None: return str(val)
        return os.getenv(key, default)
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 757-772
  excerpt: |
    self.default_project = default_project or _cfg("JIRA_DEFAULT_PROJECT", "NAV")
    self.default_issue_type = _cfg("JIRA_DEFAULT_ISSUE_TYPE", "Task")
    self.default_labels = _parse_csv(_cfg("JIRA_DEFAULT_LABELS", "") or "")
    self.default_components = _parse_csv(_cfg("JIRA_DEFAULT_COMPONENTS", "") or "")
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 774-803
  symbol: `workflow_paths`
  excerpt: |
    self.workflow_paths: Dict[str, List[str]] = {}
    _default_path = _cfg("JIRA_WORKFLOW_PATH")
    ...
    _prefix = "JIRA_WORKFLOW_PATH_"
    for _env_key, _env_val in os.environ.items():
        if _env_key.startswith(_prefix) and _env_val:
            self.workflow_paths[_env_key[len(_prefix):].upper()] = self._parse_workflow_path(_env_val)
    for _project, _value in (workflow_paths or {}).items():  # programmatic override wins
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 659-664
  symbol: `JiraToolkit.config_model`
  excerpt: |
    config_model = JiraToolkitConfig
    options_params = frozenset({"default_project"})
    secret_params = frozenset({"password", "token", ...})
- path: `packages/ai-parrot-tools/src/parrot_tools/jira_config.py`
  lines: 12-24
  symbol: `JiraToolkitConfig`
  excerpt: |
    class JiraToolkitConfig(BaseModel):
        model_config = ConfigDict(extra="forbid")
        server_url: str | None; auth_type: Literal[...] | None; username; password; token
        default_project: str | None = Field(default=None, description="Default project key")
        verify_credentials: bool = True
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 693-696
  symbol: `_DEFAULT_WORKFLOW_KEY`
  excerpt: |
    _DEFAULT_WORKFLOW_KEY = "_DEFAULT"
