import pytest

from navrules.registry import FunctionRegistry


async def valid_fn(user, env, conn, **kwargs):
    return 1


def sync_fn(user, env, conn):
    return 1


async def short_fn(user):
    return 1


class TestRegister:
    def test_register_works(self):
        # Regression: the rewards original wrote to an uninitialized
        # self._functions and raised AttributeError.
        registry = FunctionRegistry()
        registry.register("my.fn", valid_fn)
        assert registry.get_function("my.fn") is valid_fn
        assert "my.fn" in registry.list_functions()

    def test_register_rejects_sync(self):
        registry = FunctionRegistry()
        with pytest.raises(ValueError, match="must be async"):
            registry.register("bad", sync_fn)

    def test_register_rejects_short_signature(self):
        registry = FunctionRegistry()
        with pytest.raises(ValueError, match="at least"):
            registry.register("bad", short_fn)


class TestLoadByPath:
    def test_load_real_function(self):
        registry = FunctionRegistry()
        fn = registry.load_function(f"{__name__}.valid_fn")
        assert fn is valid_fn

    def test_load_missing_returns_none(self):
        registry = FunctionRegistry()
        assert registry.load_function("no.such.module.fn") is None

    def test_allowed_prefixes_enforced(self):
        registry = FunctionRegistry(allowed_prefixes=("myapp.",))
        assert registry.load_function(f"{__name__}.valid_fn") is None

    def test_cache_survives_clear_for_registered(self):
        registry = FunctionRegistry()
        registry.register("keep.me", valid_fn)
        registry.load_function(f"{__name__}.valid_fn")
        registry.clear_cache()
        assert registry.get_function("keep.me") is valid_fn
        assert f"{__name__}.valid_fn" not in registry.list_functions()
