---
id: F013
query_id: Q013
type: read
intent: Read existing toolkit tests to learn the mocking pattern and current assertions.
executed_at: 2026-10-07T22:57:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F013 — Tests pin the exact __init__ signature; _FakeJIRA / AsyncMock pattern

## Summary

`packages/ai-parrot-tools/tests/unit/` has three Jira test modules (delegation, oauth, verify_credentials). `test_jiratoolkit_delegation.py` asserts `tuple(inspect.signature(JiraToolkit.__init__).parameters) == INIT_PARAMS_BASELINE` — a 15-entry tuple ending in `workflow_paths, verify_credentials, kwargs`. Adding a new constructor kwarg (e.g. `templates_dir`) is a deliberate baseline change and MUST update that tuple (the docstring says regenerate only on intentional change). Mocking: `_FakeJIRA` drop-in for `jira.JIRA` + `_FakeReadInterface` with AsyncMocks; comment-attachment tests live in core `packages/ai-parrot/tests/test_jira_comment_attachments.py`.

## Citations

- path: `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py`
  lines: 23-39
  symbol: `INIT_PARAMS_BASELINE`
  excerpt: |
    INIT_PARAMS_BASELINE: tuple[str, ...] = ("self", "server_url", "auth_type", "username", "password",
        "token", "oauth_consumer_key", "oauth_key_cert", "oauth_access_token", "oauth_access_token_secret",
        "default_project", "credential_resolver", "workflow_paths", "verify_credentials", "kwargs")
- path: `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py`
  lines: 105-107
  symbol: `test_init_signature_unchanged`
  excerpt: |
    def test_init_signature_unchanged(self):
        params = tuple(inspect.signature(JiraToolkit.__init__).parameters)
        assert params == INIT_PARAMS_BASELINE
- path: `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py`
  lines: 42-60
  symbol: `_FakeJIRA`
  excerpt: |
    class _FakeJIRA:  # Drop-in replacement for jira.JIRA
    class _FakeReadInterface:  # attach_client = MagicMock(); fetch_issue_object = AsyncMock(...)
- path: `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py`
- path: `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_verify_credentials.py`
