"""The host-declared ``request["tenant_context"]`` wins tenant resolution.

Rationale (mirrors ``_utils._get_request_tenant`` step 0): the session's
``programs[0]`` is an arbitrarily ordered DEFAULT — a caller with eleven
programmes is a member of all eleven — so it can never state which
programme a request is about. The host application authorizes a claim
(something this library cannot do: it knows nothing about the host's
entitlement model) and declares the result on the request. When it does,
that declaration must win; when it does not, behaviour is byte-identical
to before this key existed.
"""

from unittest.mock import Mock

from aiohttp.test_utils import make_mocked_request

from parrot_formdesigner.api._utils import _get_request_tenant


def _request_with(tenant_context=None, session_programs=None, default_tenant=None):
    app = {}
    if default_tenant is not None:
        registry = Mock()
        registry.default_tenant = default_tenant
        app["form_registry"] = registry
    request = make_mocked_request("GET", "/api/v1/forms", app=app)
    if tenant_context is not None:
        request["tenant_context"] = tenant_context
    if session_programs is not None:
        request.session = {"session": {"programs": session_programs}}
    return request


def test_host_declared_context_wins_over_session_programs():
    request = _request_with(
        tenant_context="flexroc", session_programs=["walmart", "flexroc"]
    )
    assert _get_request_tenant(request) == "flexroc"


def test_without_context_session_programs_zero_still_wins():
    """No key set -> the pre-existing behaviour, byte-identical."""
    request = _request_with(session_programs=["walmart", "flexroc"])
    assert _get_request_tenant(request) == "walmart"


def test_without_context_or_session_registry_default_survives():
    request = _request_with(default_tenant="navigator")
    assert _get_request_tenant(request) == "navigator"


def test_empty_context_is_ignored_never_returned():
    """A falsy declaration ('' or None) must not shadow the fallbacks."""
    request = _request_with(tenant_context="", default_tenant="navigator")
    assert _get_request_tenant(request) == "navigator"
