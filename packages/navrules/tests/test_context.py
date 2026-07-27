from datetime import date, datetime, timezone

from navrules.context import EvalContext
from navrules.environment import Environment

SATURDAY = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)


class TestBasics:
    def test_missing_key_resolves_false(self):
        ctx = EvalContext(user={"a": 1})
        assert ctx["nope"] is False

    def test_attribute_access(self):
        ctx = EvalContext(user={"a": 1}, session={"email": "x@y.z"})
        assert ctx.user == {"a": 1}
        assert ctx.session["email"] == "x@y.z"

    def test_set_and_columns(self):
        ctx = EvalContext()
        ctx.set("worked_hours", 9)
        assert "worked_hours" in ctx
        assert ctx["worked_hours"] == 9

    def test_session_object_key_extraction(self):
        session = {"auth_obj": {"user_id": 42}}
        ctx = EvalContext(session=session, session_object_key="auth_obj")
        assert ctx.userinfo == {"user_id": 42}

    def test_user_keys_from_dict(self):
        ctx = EvalContext(user={"a": 1, "b": 2})
        assert set(ctx.store["user_keys"]) == {"a", "b"}


class TestFromUser:
    def test_synthesizes_session(self):
        user = {"email": "e@x.co", "user_id": 7, "job_code": "TECH1"}
        ctx = EvalContext.from_user(user, worked_hours=8.5)
        assert ctx.session["email"] == "e@x.co"
        assert ctx.session["job_code"] == "TECH1"
        assert ctx["worked_hours"] == 8.5

    def test_object_user(self):
        class U:
            def __init__(self):
                self.email = "o@x.co"
                self.job_code = "MGR"
                self._private = "hidden"

        ctx = EvalContext.from_user(U())
        assert ctx.session["email"] == "o@x.co"
        assert "_private" not in ctx.session


class TestFlatten:
    def test_prefixes_and_bare_aliases(self):
        ctx = EvalContext.from_user(
            {"email": "e@x.co", "job_code": "TECH1"}, worked_hours=9
        )
        env = Environment(timestamp=SATURDAY)
        flat = ctx.flatten(env)
        assert flat["ctx.job_code"] == "TECH1"
        assert flat["ctx.worked_hours"] == 9
        assert flat["env.is_weekend"] is True
        assert flat["job_code"] == "TECH1"  # bare alias
        assert flat["quarter"] == "Q3"  # env bare alias

    def test_ctx_wins_bare_collision_with_env(self):
        ctx = EvalContext(user={"hour": 99})
        env = Environment(timestamp=SATURDAY)
        flat = ctx.flatten(env)
        assert flat["hour"] == 99
        assert flat["env.hour"] == 14

    def test_datetime_normalization(self):
        ctx = EvalContext(
            user={"start_date": date(2020, 3, 1)},
            hired_at=datetime(2020, 3, 1, 9, 0, tzinfo=timezone.utc),
        )
        flat = ctx.flatten()
        assert flat["ctx.start_date"] == "2020-03-01"
        assert flat["ctx.hired_at"] == "2020-03-01T09:00:00+00:00"

    def test_non_scalars_excluded(self):
        ctx = EvalContext(user={"nested": {"deep": 1}, "ok": 5})
        flat = ctx.flatten()
        assert "ctx.nested" not in flat
        assert flat["ctx.ok"] == 5

    def test_user_overrides_session_kwargs_override_user(self):
        ctx = EvalContext(
            user={"job_code": "FROM_USER"},
            session={"job_code": "FROM_SESSION"},
            job_code="FROM_KWARGS",
        )
        assert ctx.flatten()["ctx.job_code"] == "FROM_KWARGS"


class TestComputedCache:
    async def test_get_computed_uses_registry_and_cache(self):
        from navrules.registry import FunctionRegistry

        calls = []

        async def fn(user, env, conn, **kwargs):
            calls.append(1)
            return 42

        registry = FunctionRegistry()
        registry.register("my.fn", fn)
        ctx = EvalContext(user={"a": 1})
        env = Environment()
        assert await ctx.get_computed("my.fn", env, registry=registry) == 42
        assert await ctx.get_computed("my.fn", env, registry=registry) == 42
        assert len(calls) == 1  # cached

    async def test_get_computed_missing_function(self):
        ctx = EvalContext()
        env = Environment()
        assert await ctx.get_computed("no.such.fn", env) is None
