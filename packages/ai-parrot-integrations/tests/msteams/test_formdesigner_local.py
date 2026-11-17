"""FEAT-734 — LocalFormReader: membership before registry, signed renders."""

import pytest
from parrot_formdesigner.core.schema import FieldType, FormField, FormSchema, FormSection
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsSubmitEnvelope
from parrot_formdesigner.services.registry import FormRegistry

from parrot.integrations.msteams.formdesigner_client import FormDesignerError
from parrot.integrations.msteams.formdesigner_local import LocalFormReader

TENANT = "acme"
SECRET = "s3cret"
BASE = "https://forms.example.com"


class Authorizer:
    def __init__(self, allow=True, boom=False):
        self.calls, self.allow, self.boom = [], allow, boom

    async def require_membership(self, *, tenant, bearer_token, user_id):
        self.calls.append((tenant, user_id))
        if self.boom:
            raise RuntimeError("authority down")
        if not self.allow:
            raise PermissionError("not a member")


class SpyRegistry:
    """Wraps a FormRegistry and counts calls."""

    def __init__(self, inner):
        self.inner, self.count = inner, 0

    async def list_forms(self, **kw):
        self.count += 1
        return await self.inner.list_forms(**kw)

    async def get(self, *a, **kw):
        self.count += 1
        return await self.inner.get(*a, **kw)

    async def get_by_slug(self, *a, **kw):
        self.count += 1
        return await self.inner.get_by_slug(*a, **kw)


def _form(n_sections=1, public=False, form_id="survey"):
    sections = [
        FormSection(
            section_id=f"s{i}",
            fields=[FormField(field_id=f"f{i}", field_type=FieldType.TEXT, label=f"F{i}")],
        )
        for i in range(n_sections)
    ]
    return FormSchema(form_id=form_id, title="Survey", sections=sections, tenant=TENANT, is_public=public)


async def _setup(form, authorizer, *, secret=SECRET, base=BASE, user="u1"):
    registry = FormRegistry()
    await registry.register(form, tenant=TENANT)
    spy = SpyRegistry(registry)
    reader = LocalFormReader(
        spy,
        authorizer=authorizer,
        user_id_resolver=lambda: user,
        public_base_url=base,
        signing_secret=secret,
    )
    return reader, spy


async def test_denied_before_registry():
    form = _form()
    for authorizer in (None, Authorizer(allow=False), Authorizer(boom=True)):
        reader, spy = await _setup(form, authorizer)
        with pytest.raises(FormDesignerError) as exc:
            await reader.list_forms(tenant=TENANT, bearer_token="tok")
        assert exc.value.status == 403
        with pytest.raises(FormDesignerError):
            await reader.get_form(tenant=TENANT, form_uid=form.form_uid, bearer_token="tok")
        with pytest.raises(FormDesignerError):
            await reader.get_form_by_slug(tenant=TENANT, slug="survey", bearer_token="tok")
        assert spy.count == 0
    reader, spy = await _setup(form, Authorizer())
    with pytest.raises(FormDesignerError) as exc:
        await reader.list_forms(tenant=TENANT, bearer_token=None)
    assert exc.value.status == 403
    reader, spy = await _setup(form, Authorizer(), user=None)
    with pytest.raises(FormDesignerError):
        await reader.list_forms(tenant=TENANT, bearer_token="tok")
    assert spy.count == 0


async def test_authorized_list_and_resolve():
    form = _form()
    auth = Authorizer()
    reader, spy = await _setup(form, auth)
    rows = await reader.list_forms(tenant=TENANT, bearer_token="tok")
    assert [r.form_uid for r in rows] == [form.form_uid]
    assert rows[0].source == "memory"
    got = await reader.get_form(tenant=TENANT, form_uid=form.form_uid, bearer_token="tok")
    assert got.form_uid == form.form_uid
    desc = await reader.get_form_by_slug(tenant=TENANT, slug="survey", bearer_token="tok")
    assert desc is not None and desc.form_id == "survey"
    assert await reader.get_form_by_slug(tenant=TENANT, slug="nope", bearer_token="tok") is None
    assert auth.calls and auth.calls[0] == (TENANT, "u1")


async def test_public_form_still_requires_membership():
    form = _form(public=True)
    reader, spy = await _setup(form, Authorizer(allow=False))
    with pytest.raises(FormDesignerError) as exc:
        await reader.get_form(tenant=TENANT, form_uid=form.form_uid, bearer_token="tok")
    assert exc.value.status == 403
    assert spy.count == 0


async def test_render_signed_with_agent_secret():
    form = _form()
    reader, _ = await _setup(form, Authorizer())
    card = await reader.render_teams(tenant=TENANT, form_uid=form.form_uid, bearer_token="tok")
    env = TeamsSubmitEnvelope.model_validate(card.metadata["envelope"])
    assert env.verify(SECRET)
    assert not env.verify("other")


async def test_render_without_secret_refuses():
    form = _form()
    for kwargs in ({"secret": None}, {"secret": ""}, {"base": None}):
        reader, spy = await _setup(form, Authorizer(), **kwargs)
        with pytest.raises(FormDesignerError) as exc:
            await reader.render_teams(tenant=TENANT, form_uid=form.form_uid, bearer_token="tok")
        assert exc.value.status == 500


async def test_section_render_metadata_and_terminal_envelope():
    form = _form(n_sections=3)
    reader, _ = await _setup(form, Authorizer())
    cards = [
        await reader.render_teams(tenant=TENANT, form_uid=form.form_uid, bearer_token="tok", section_index=i)
        for i in range(3)
    ]
    for i, card in enumerate(cards):
        assert card.metadata["section_index"] == i
        assert card.metadata["total_sections"] == 3
        assert card.metadata["form_version"]
        assert TeamsSubmitEnvelope.model_validate(card.metadata["envelope"]).verify(SECRET)
        has_env = ENVELOPE_KEY in str(card.content.get("actions", []))
        assert has_env == (i == 2)
    with pytest.raises(FormDesignerError) as exc:
        await reader.render_teams(tenant=TENANT, form_uid=form.form_uid, bearer_token="tok", section_index=3)
    assert exc.value.status == 400
