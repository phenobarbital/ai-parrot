"""FEAT-421 / TASK-2198 — host middleware declares the browsed programme as
``request["tenant_context"]`` after authorizing the ``?program_slug=`` claim.

parrot-formdesigner (#1146) honors ``request["tenant_context"]`` over the
session's ``programs[0]``, but deliberately does NOT authorize it — that is the
host's job. ``forms_tenant_context_middleware`` (app.py) is that host piece: it
validates ``program_slug`` against the caller's session (member OR superuser)
and only then declares it. These tests pin that authorization boundary.

Fixes AI-created/edited forms landing under the wrong tenant (NAV-9372/9370).
"""

from aiohttp.test_utils import make_mocked_request

from app import forms_tenant_context_middleware


async def _resolve(program_slug, *, programs=None, superuser=False):
    """Run the middleware over a mocked forms request and return the
    ``tenant_context`` it declared (or ``None``)."""
    path = "/api/v1/forms"
    if program_slug is not None:
        path += f"?program_slug={program_slug}"
    request = make_mocked_request("GET", path)
    if programs is not None or superuser:
        request.session = {  # type: ignore[attr-defined]
            "session": {"programs": programs or [], "superuser": superuser}
        }

    async def _handler(req):
        return req

    returned = await forms_tenant_context_middleware(request, _handler)
    return returned.get("tenant_context")


async def test_member_declares_requested_programme():
    assert await _resolve("epson", programs=["navigator", "epson"]) == "epson"


async def test_superuser_declares_any_programme():
    assert await _resolve("epson", programs=["navigator"], superuser=True) == "epson"


async def test_non_member_non_superuser_declares_nothing():
    # Claim is ignored → parrot falls back to its own resolution (no cross-tenant).
    assert await _resolve("epson", programs=["navigator"], superuser=False) is None


async def test_no_program_slug_declares_nothing():
    assert await _resolve(None, programs=["navigator", "epson"]) is None


async def test_no_session_declares_nothing():
    assert await _resolve("epson") is None


async def test_empty_programs_non_superuser_declares_nothing():
    assert await _resolve("epson", programs=[], superuser=False) is None
