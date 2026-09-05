"""Regression tests for the ``_fallback_model`` constructor-shadowing fix
(FEAT-438 TASK-2299 / spec G5).

``AbstractClient.__init__`` previously did an unconditional
``self._fallback_model = kwargs.get('fallback_model', None)``, which
silently reset any subclass's class-level ``_fallback_model`` default to
``None`` on every instance unless the caller explicitly passed
``fallback_model=``. Fixed so the assignment only happens when
``fallback_model`` is explicitly present in kwargs (including explicit
``None``); otherwise attribute reads fall through to the class-level
default (now declared on ``AbstractClient`` itself so ``getattr`` never
fails for clients that don't set their own).
"""

from parrot.clients.base import AbstractClient


class _Stub(AbstractClient):
    """Minimal concrete AbstractClient subclass for instantiation."""

    client_type = "stub"

    async def get_client(self):  # pragma: no cover - not exercised here
        return None

    async def ask(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def ask_stream(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def resume(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def invoke(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError


class _WithFallback(_Stub):
    _fallback_model = "class-level-fallback"


def test_class_attr_survives_without_kwarg():
    c = _WithFallback()
    assert c._fallback_model == "class-level-fallback"


def test_explicit_kwarg_wins():
    c = _WithFallback(fallback_model="override")
    assert c._fallback_model == "override"


def test_explicit_none_wins():
    c = _WithFallback(fallback_model=None)
    assert c._fallback_model is None


def test_no_class_level_default_falls_through_to_none():
    """A subclass declaring no _fallback_model at all must not AttributeError —
    AbstractClient itself declares the class-level None default."""
    c = _Stub()
    assert c._fallback_model is None


def test_mantle_no_longer_needs_workaround():
    """BedrockMantleClient no longer declares a truthy ``_fallback_model``
    (its only candidate, "google.gemma-4-26b-a4b", 400s as unsupported on
    Mantle's chat-completions route — found live 2026-09-05, see
    nova/mantle.py). This still guards the FEAT-438 G5 fix: without it,
    __init__'s old unconditional ``kwargs.get('fallback_model', None)``
    would be indistinguishable from the declared class-level default here
    since both are ``None`` — real discriminating coverage (a truthy
    class-level default surviving unshadowed) lives in
    test_class_attr_survives_without_kwarg above."""
    from parrot.clients.amazon.nova.mantle import BedrockMantleClient

    c = BedrockMantleClient(api_key="k")
    assert c._fallback_model is None
