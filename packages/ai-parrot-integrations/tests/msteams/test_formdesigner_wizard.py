"""FEAT-734 M5 — WizardStore."""

import uuid

from parrot.integrations.msteams.formdesigner_wizard import WizardStore

UID = uuid.uuid4()


def _start(store, conv="c1", uid=UID):
    return store.start(
        conversation_id=conv, form_uid=uid, tenant="acme", total_sections=3, owner_user_id="u1", form_version="1.0"
    )


def test_wizard_advance_accumulates_answers():
    store = WizardStore()
    state = _start(store)
    store.advance(state, {"a": 1})
    store.advance(state, {"b": 2})
    got = store.get(conversation_id="c1", form_uid=UID)
    assert got is state
    assert got.answers == {"a": 1, "b": 2}
    assert got.section_index == 2


def test_wizard_expiry_returns_none(monkeypatch):
    store = WizardStore(ttl_seconds=10)
    monkeypatch.setattr(store, "_now", lambda: 1000.0)
    _start(store)
    monkeypatch.setattr(store, "_now", lambda: 1011.0)
    assert store.get(conversation_id="c1", form_uid=UID) is None
    assert len(store) == 0


def test_wizard_eviction_bounded():
    store = WizardStore(max_items=2)
    for conv in ("c1", "c2", "c3"):
        _start(store, conv=conv)
        assert len(store) <= 2
    assert store.get(conversation_id="c1", form_uid=UID) is None
    assert store.get(conversation_id="c2", form_uid=UID) is not None
    assert store.get(conversation_id="c3", form_uid=UID) is not None


def test_wizard_restart_gets_new_wizard_id():
    store = WizardStore()
    first = _start(store)
    store.advance(first, {"a": 1})
    second = _start(store)
    assert second.wizard_id != first.wizard_id
    assert second.section_index == 0
    assert second.answers == {}
    assert store.get(conversation_id="c1", form_uid=UID) is second


def test_wizard_discard_and_finish():
    store = WizardStore()
    state = _start(store)
    store.advance(state, {"a": 1})
    assert store.finish(conversation_id="c1", form_uid=UID) == {"a": 1}
    assert store.get(conversation_id="c1", form_uid=UID) is None
    assert store.finish(conversation_id="c1", form_uid=UID) == {}
    _start(store)
    store.discard(conversation_id="c1", form_uid=UID)
    assert store.get(conversation_id="c1", form_uid=UID) is None
