"""Unit tests for JiraToolkitBinder + FakeJiraClient + StaticResolver (TASK-1420).

Uses lightweight stub toolkits to avoid importing the full JiraToolkit
(which has optional deps not available in the test venv).
"""
import pytest

from parrot.eval import DictStateBackend, JiraToolkitBinder
from parrot.eval.sandbox.fakes import FakeJiraClient, StaticResolver


class _StubJiraToolkit:
    """Minimal stub mimicking JiraToolkit's injection points."""

    def __init__(self, auth_type: str = "basic_auth") -> None:
        self.jira = None
        self.auth_type = auth_type
        self.credential_resolver = None
        self._client_cache: dict = {}
        self._http_called: bool = False


async def test_jira_binder_sets_jira_attribute():
    """Binder pre-seeds toolkit.jira with FakeJiraClient."""
    toolkit = _StubJiraToolkit()
    backend = DictStateBackend()
    binder = JiraToolkitBinder()
    binder.bind(toolkit, backend)

    assert isinstance(toolkit.jira, FakeJiraClient)


async def test_jira_binder_no_network_call():
    """Binder does not make any network calls (no credential_resolver.resolve)."""
    network_calls = []

    class TrackingResolver:
        async def resolve(self, channel, user_id):
            network_calls.append((channel, user_id))
            return None

    toolkit = _StubJiraToolkit()
    toolkit.credential_resolver = TrackingResolver()
    backend = DictStateBackend()
    binder = JiraToolkitBinder()
    binder.bind(toolkit, backend)

    # No resolver.resolve() should have been called during bind
    assert network_calls == []


async def test_fake_jira_client_assign_mutates_backend():
    """FakeJiraClient._assign_async updates the issues collection."""
    backend = DictStateBackend()
    await backend.reset({"issues": {"PROJ-1": {"assignee": None, "type": "bug"}}})

    client = FakeJiraClient(backend)
    await client._assign_async("PROJ-1", "oncall")

    snap = await backend.snapshot()
    assert snap["issues"]["PROJ-1"]["assignee"] == "oncall"


async def test_fake_jira_client_transition_mutates_backend():
    """FakeJiraClient._transition_async updates issue status."""
    backend = DictStateBackend()
    await backend.reset({"issues": {"PROJ-1": {"status": "open"}}})

    client = FakeJiraClient(backend)
    await client._transition_async("PROJ-1", "done")

    snap = await backend.snapshot()
    assert snap["issues"]["PROJ-1"]["status"] == "done"


async def test_fake_jira_client_search():
    """FakeJiraClient._search_async returns all issues (no JQL filter)."""
    backend = DictStateBackend()
    await backend.reset({
        "issues": {
            "PROJ-1": {"type": "bug"},
            "PROJ-2": {"type": "task"},
        }
    })

    client = FakeJiraClient(backend)
    results = await client._search_async("project = PROJ", max_results=50)
    assert len(results) == 2


async def test_static_resolver_returns_token():
    """StaticResolver.resolve returns a token set without network calls."""
    backend = DictStateBackend()
    client = FakeJiraClient(backend)
    resolver = StaticResolver(client, access_token="test-token-1234567890abcdef")

    token_set = await resolver.resolve("test-channel", "test-user")
    assert token_set.access_token == "test-token-1234567890abcdef"


async def test_jira_binder_oauth2_seeds_cache():
    """For oauth2_3lo mode, the binder pre-seeds _client_cache."""
    toolkit = _StubJiraToolkit(auth_type="oauth2_3lo")
    backend = DictStateBackend()
    binder = JiraToolkitBinder()
    binder.bind(toolkit, backend)

    # Cache should have at least one entry
    assert len(toolkit._client_cache) >= 1
    # The stored client should be the FakeJiraClient
    for key, (cached_client, token_hash) in toolkit._client_cache.items():
        assert isinstance(cached_client, FakeJiraClient)


async def test_binder_bind_returns_fake_on_non_oauth2():
    """For basic_auth mode, toolkit.jira is the FakeJiraClient directly."""
    toolkit = _StubJiraToolkit(auth_type="basic_auth")
    backend = DictStateBackend()
    binder = JiraToolkitBinder()
    binder.bind(toolkit, backend)

    # Direct attribute — no cache lookup needed
    assert isinstance(toolkit.jira, FakeJiraClient)
    assert toolkit.jira._backend is backend
