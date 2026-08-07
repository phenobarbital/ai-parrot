"""Contract tests for the `budget-variance-daily.yaml` example recipe (FEAT-420)."""

from pathlib import Path

from parrot.outputs.a2ui.recipes.models import InfographicRecipe

# Anchored to this test file's own location rather than the process cwd —
# see the "navconfig os.chdir breaks relative paths in worktree tests"
# lesson (importing `parrot.outputs...` can chdir away from a git worktree).
_REPO_ROOT = Path(__file__).resolve().parents[6]
YAML = _REPO_ROOT / "examples" / "infographic_recipes" / "budget-variance-daily.yaml"


class TestExampleRecipeYaml:
    def test_loads_at_schema_v1(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())
        assert recipe.schema_version == 1

    def test_declares_narrative(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())
        assert recipe.narrative is not None
        assert recipe.narrative.skill == "budget-narrative"
        assert recipe.narrative.facts_key == "narrative_facts"

    def test_narrative_facts_ordered_after_inputs(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())
        names = [t.transformer for t in recipe.transforms]
        i = names.index("narrative_facts")
        for dep in ("variance_analysis", "top_movers", "division_breakdown"):
            assert names.index(dep) < i

    def test_snapshot_col_set_on_every_finance_step(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())
        finance = {"day_totals", "division_breakdown", "variance_analysis", "top_movers"}
        cols = {
            t.params.get("snapshot_col") for t in recipe.transforms if t.transformer in finance
        }
        assert len(cols) == 1 and None not in cols, f"inconsistent snapshot_col: {cols}"

    def test_has_an_optional_narrative_bind(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())

        found = []

        def walk(v):
            if isinstance(v, dict):
                if "$bind" in v and "/narrative" in str(v["$bind"]):
                    found.append(v.get("optional"))
                for i in v.values():
                    walk(i)
            elif isinstance(v, list):
                for i in v:
                    walk(i)

        walk(recipe.layout.properties)
        assert found and all(f is True for f in found)

    def test_delivery_still_null(self):
        assert InfographicRecipe.from_yaml(YAML.read_text()).render.delivery is None
