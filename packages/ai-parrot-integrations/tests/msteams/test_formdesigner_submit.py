"""Unit tests for msteams.formdesigner_submit (FEAT-551 TASK-3150) — no botbuilder needed."""

import uuid
import pytest
import asyncio
from aiohttp import web
from parrot.integrations.msteams.formdesigner_submit import (
    EnvelopeRejected,
    RecentActivityCache,
    SubmitOutcome,
    build_reply_card,
    extract_answers,
    parse_envelope,
    post_submission,
    verify_envelope,
)
from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsSubmitEnvelope

pytestmark = pytest.mark.asyncio
FORM_UID = uuid.uuid4()


def _env(**over) -> TeamsSubmitEnvelope:
    base = dict(
        form_uid=FORM_UID,
        tenant="navigator",
        form_version="1.0",
        is_public=True,
        submit_url=f"https://forms.test/api/v1/navigator/forms/{FORM_UID}/data",
        form_url=f"https://forms.test/navigator/forms/{FORM_UID}",
    )
    base.update(over)
    return TeamsSubmitEnvelope(**base)


def test_parse_envelope_rejects_malformed():
    with pytest.raises(EnvelopeRejected):
        parse_envelope({"_action": "submit"})
    with pytest.raises(EnvelopeRejected):
        parse_envelope({ENVELOPE_KEY: {"form_uid": "nope"}})
    assert parse_envelope({ENVELOPE_KEY: _env().model_dump(mode="json")}).tenant == "navigator"


@pytest.mark.parametrize(
    "over,reason",
    [
        ({"submit_url": f"http://forms.test/api/v1/navigator/forms/{FORM_UID}/data"}, "https"),
        ({"submit_url": f"https://evil.test/api/v1/navigator/forms/{FORM_UID}/data"}, "not allowed"),
        ({"submit_url": f"https://forms.test/api/v1/other/forms/{FORM_UID}/data"}, "does not match"),
        ({"submit_url": f"https://forms.test/api/v1/navigator/forms/{uuid.uuid4()}/data"}, "does not match"),
    ],
)
def test_verify_envelope_rules(over, reason):
    with pytest.raises(EnvelopeRejected, match=reason):
        verify_envelope(_env(**over), allowed_hosts=["forms.test"], secret=None)


def test_verify_envelope_signature():
    signed = _env().sign("s3cr3t")
    verify_envelope(signed, allowed_hosts=["FORMS.test"], secret="s3cr3t")
    with pytest.raises(EnvelopeRejected, match="signature"):
        verify_envelope(_env(), allowed_hosts=["forms.test"], secret="s3cr3t")


def test_extract_answers_keeps_underscore_field_ids():
    data = {"_action": "submit", ENVELOPE_KEY: {}, "_department": "ops", "age": "42", "ok": "true"}
    assert extract_answers(data) == {"_department": "ops", "age": "42", "ok": "true"}


async def test_post_submission_outcomes(aiohttp_client):
    async def handler(request):
        data = await request.json()
        marker = data.get("marker")
        auth_header = request.headers.get("Authorization")

        if marker == "auth_check":
            if auth_header == "Bearer valid_token":
                return web.json_response({"submission_id": "sub_auth", "is_valid": True})
            return web.json_response({"error": "unauthorized"}, status=401)

        if marker == "200":
            return web.json_response({"submission_id": "sub_123", "is_valid": True})
        elif marker == "422":
            return web.json_response({"is_valid": False, "errors": {"email": ["Invalid email"]}}, status=422)
        elif marker == "403":
            return web.json_response({"error": "Forbidden"}, status=403)
        elif marker == "redirect":
            return web.Response(status=302, headers={"Location": "/somewhere"})
        elif marker == "timeout":
            await asyncio.sleep(0.5)
            return web.json_response({"ok": True})
        elif marker == "large":
            return web.Response(text="x" * 2000, status=200)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/submit", handler)
    client = await aiohttp_client(app)

    # 200 OK
    env = _env(submit_url=f"{client.make_url('/submit')}")
    outcome = await post_submission(client.session, env, {"marker": "200"}, bearer_token=None, timeout=1.0)
    assert outcome.status == 200
    assert outcome.body == {"submission_id": "sub_123", "is_valid": True}

    # 422 Validation Error
    outcome = await post_submission(client.session, env, {"marker": "422"}, bearer_token=None, timeout=1.0)
    assert outcome.status == 422
    assert outcome.body == {"is_valid": False, "errors": {"email": ["Invalid email"]}}

    # 403 Forbidden
    outcome = await post_submission(client.session, env, {"marker": "403"}, bearer_token=None, timeout=1.0)
    assert outcome.status == 403

    # Redirect (should not be followed, returns 302)
    outcome = await post_submission(client.session, env, {"marker": "redirect"}, bearer_token=None, timeout=1.0)
    assert outcome.status == 302

    # Timeout
    outcome = await post_submission(client.session, env, {"marker": "timeout"}, bearer_token=None, timeout=0.1)
    assert outcome.status == 0
    assert outcome.error == "TimeoutError"

    # Large response
    outcome = await post_submission(
        client.session, env, {"marker": "large"}, bearer_token=None, timeout=1.0, max_response_bytes=100
    )
    assert outcome.status == 200
    assert outcome.error == "response too large"

    # Auth check
    outcome = await post_submission(
        client.session, env, {"marker": "auth_check"}, bearer_token="valid_token", timeout=1.0
    )
    assert outcome.status == 200
    assert outcome.body == {"submission_id": "sub_auth", "is_valid": True}


def test_build_reply_card_mapping():
    env = _env()

    # 200 OK
    card_200 = build_reply_card(SubmitOutcome(status=200, body={"submission_id": "sub_123"}), env)
    assert "sub_123" in card_200["body"][0]["text"]
    assert card_200["body"][0]["color"] == "Good"

    # 422 Validation Error
    card_422 = build_reply_card(SubmitOutcome(status=422, body={"errors": {"email": ["Invalid email"]}}), env)
    assert "validation errors" in card_422["body"][0]["text"]
    assert "email" in card_422["body"][1]["text"]
    assert "Invalid email" in card_422["body"][1]["text"]

    # 403 Forbidden
    card_403 = build_reply_card(SubmitOutcome(status=403), env)
    assert "private" in card_403["body"][0]["text"]

    # 404 Not Found
    card_404 = build_reply_card(SubmitOutcome(status=404), env)
    assert "could not be found" in card_404["body"][0]["text"]

    # 0 / Timeout / Error
    card_err = build_reply_card(SubmitOutcome(status=0, error="TimeoutError"), env)
    assert "TimeoutError" in card_err["body"][0]["text"]


def test_recent_activity_cache():
    c = RecentActivityCache(ttl_seconds=60)
    assert c.seen("a") is False
    assert c.seen("a") is True
    assert c.seen("b") is False


def test_config_from_dict_formdesigner_fields():
    cfg = MSTeamsAgentConfig.from_dict(
        "bot", {"formdesigner_allowed_hosts": ["forms.test"], "formdesigner_submit_timeout": "5"}
    )
    assert cfg.formdesigner_allowed_hosts == ["forms.test"]
    assert cfg.formdesigner_submit_timeout == 5.0
    assert MSTeamsAgentConfig.from_dict("bot", {}).formdesigner_allowed_hosts in (None, [])
