import pytest

from navrules import ConditionRule, RuleLoader, RuleLoadError
from navrules.abstract import AbstractRule


class TestSpecShapes:
    def test_string_spec(self):
        rule = RuleLoader().load("ConditionRule")
        assert isinstance(rule, ConditionRule)

    def test_list_spec_with_kwargs(self):
        spec = ["ConditionRule", {"priority": 5, "result": "X"}]
        rule = RuleLoader().load(spec)
        assert rule.priority == 5
        assert rule.result == "X"
        # Original spec list must NOT be mutated (historical pop() bug)
        assert spec[0] == "ConditionRule"

    def test_dict_spec(self):
        rule = RuleLoader().load(
            {"rule_type": "ConditionRule", "priority": 7}
        )
        assert rule.priority == 7

    def test_dict_spec_type_alias(self):
        rule = RuleLoader().load({"type": "ConditionRule"})
        assert isinstance(rule, ConditionRule)

    def test_instance_passthrough(self):
        rule = ConditionRule(name="x")
        assert RuleLoader().load(rule) is rule


class TestErrors:
    def test_empty_list_raises(self):
        with pytest.raises(RuleLoadError, match="Empty rule list"):
            RuleLoader().load([])

    def test_missing_rule_type_raises(self):
        with pytest.raises(RuleLoadError, match="rule_type"):
            RuleLoader().load({"priority": 1})

    def test_unknown_class_raises(self):
        with pytest.raises(RuleLoadError, match="not found"):
            RuleLoader().load("NoSuchRule")

    def test_bad_kwargs_raise(self):
        class Strict(AbstractRule):
            def __init__(self, conditions=None, *, mandatory, **kwargs):
                super().__init__(conditions, **kwargs)

            def fits(self, ctx, env):
                return True

            async def evaluate(self, ctx, env):
                return True

        loader = RuleLoader(types={"Strict": Strict})
        with pytest.raises(RuleLoadError, match="instantiating"):
            loader.load("Strict")


class TestHooks:
    def test_defaults_injector(self):
        def injector(name, kwargs):
            if name == "ConditionRule":
                kwargs.setdefault("priority", 42)
            return kwargs

        loader = RuleLoader(defaults_injector=injector)
        assert loader.load("ConditionRule").priority == 42

    def test_base_conditions_merged_spec_wins(self):
        loader = RuleLoader(conditions={"a": 1, "b": 2})
        rule = loader.load(
            {"rule_type": "ConditionRule", "conditions": {"b": 99}}
        )
        assert rule.conditions == {"a": 1, "b": 99}

    def test_registered_types_take_precedence(self):
        class MyRule(ConditionRule):
            pass

        loader = RuleLoader(types={"ConditionRule": MyRule})
        assert isinstance(loader.load("ConditionRule"), MyRule)
