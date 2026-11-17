"""FEAT-734 M6 — FormDesignerToolkit with a fake reader."""

import json
import uuid
from types import SimpleNamespace

from parrot.integrations.msteams.formdesigner_client import FormDescriptor, FormDesignerError
from parrot.integrations.msteams.tools.formdesigner import FormDesignerToolkit

UID = uuid.UUID("11111111-2222-3333-4444-555555555555")


class FakeReader:
    def __init__(self, *, missing_slug: bool = False, error: FormDesignerError | None = None):
        self.calls: list[tuple] = []
        self.missing_slug = missing_slug
        self.error = error
        self.descriptor = FormDescriptor(form_uid=UID, form_id="store-visit", title="Store Visit", description="d")

    async def list_forms(self, *, tenant, bearer_token):
        self.calls.append(("list_forms", tenant, bearer_token))
        if self.error:
            raise self.error
        return [self.descriptor]

    async def get_form(self, *, tenant, form_uid, bearer_token):
        self.calls.append(("get_form", tenant, bearer_token))
        if self.error:
            raise self.error
        sub = SimpleNamespace(fields=[SimpleNamespace(field_id="a"), SimpleNamespace(field_id="b")])
        sec1 = SimpleNamespace(fields=[SimpleNamespace(field_id="x"), sub])
        sec2 = SimpleNamespace(fields=[SimpleNamespace(field_id="y")])
        return SimpleNamespace(form_id="store-visit", title="Store Visit", sections=[sec1, sec2])

    async def get_form_by_slug(self, *, tenant, slug, bearer_token):
        self.calls.append(("get_form_by_slug", tenant, bearer_token))
        return None if self.missing_slug else self.descriptor


def _toolkit(reader, *, tenant="acme", bearer="nav-tok", queue=None, accept=True):
    queue = [] if queue is None else queue
    return (
        FormDesignerToolkit(
            reader,
            tenant_resolver=lambda: tenant,
            bearer_resolver=lambda: bearer,
            enqueue_card=lambda uid: queue.append(uid) or accept,
        ),
        queue,
    )


async def test_toolkit_get_form_returns_metadata_not_card():
    tk, queue = _toolkit(FakeReader())
    result = await tk.formdesigner_get_form("store-visit")
    assert result["card_pending"] is True
    assert result["form_uid"] == str(UID)
    assert result["sections"] == 2 and result["field_count"] == 4
    assert queue == [UID]
    dumped = json.dumps(result)
    assert "body" not in result and "AdaptiveCard" not in dumped and "nav-tok" not in dumped


async def test_toolkit_list_forms_scoped_to_tenant():
    reader = FakeReader()
    tk, _ = _toolkit(reader)
    result = await tk.formdesigner_list_forms()
    assert result["tenant"] == "acme"
    assert result["forms"][0] == {
        "form_uid": str(UID),
        "form_id": "store-visit",
        "title": "Store Visit",
        "description": "d",
    }
    assert reader.calls == [("list_forms", "acme", "nav-tok")]


async def test_toolkit_without_context_fails_closed():
    reader = FakeReader()
    tk, queue = _toolkit(reader, bearer=None)
    assert await tk.formdesigner_get_form("store-visit") == {"status": "unavailable", "reason": "login_required"}
    tk2, _ = _toolkit(reader, tenant=None)
    assert await tk2.formdesigner_list_forms() == {"status": "unavailable", "reason": "tenant_unresolved"}
    assert reader.calls == [] and queue == []


async def test_toolkit_closed_turn_not_pending():
    tk, _ = _toolkit(FakeReader(), accept=False)
    result = await tk.formdesigner_get_form(str(UID))
    assert result.get("card_pending") is not True
    assert result == {"status": "unavailable", "reason": "turn_closed"}


async def test_toolkit_slug_not_found():
    tk, queue = _toolkit(FakeReader(missing_slug=True))
    assert await tk.formdesigner_get_form("nope") == {"status": "not_found", "form": "nope"}
    tk2, _ = _toolkit(FakeReader(error=FormDesignerError("x", status=404)))
    assert (await tk2.formdesigner_get_form(str(UID)))["status"] == "not_found"
    tk3, _ = _toolkit(FakeReader(error=FormDesignerError("x", status=500)))
    assert await tk3.formdesigner_list_forms() == {"status": "error", "reason": "forms_unavailable"}
    assert queue == []


def test_toolkit_exposes_exactly_two_tools():
    tk, _ = _toolkit(FakeReader())
    assert {t.name for t in tk.get_tools()} == {"formdesigner_list_forms", "formdesigner_get_form"}
