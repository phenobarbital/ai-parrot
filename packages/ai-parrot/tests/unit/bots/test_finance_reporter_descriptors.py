"""Descriptor validity + params propagation tests for `FinanceReporter` (FEAT-420 Module 8)."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

# `agents/` is a local, gitignored-by-default directory (`/agents/` in
# .gitignore; individual agent files must be `git add -f`'d to ship — see
# CLAUDE.md's "Heads-up" note on the equivalent `sdd/templates/` pattern).
# Some `parrot` submodule imports also trigger a settings bootstrap
# (`navconfig.conf`) that `os.chdir()`s to the MAIN repo checkout, which can
# make a plain `import agents.finance_reporter` resolve inconsistently when
# tests run from a git worktree. Load the module directly from this
# worktree's own file path instead — the same technique
# `tests/unit/conftest.py`'s `_load_module` helper uses for an analogous
# worktree-vs-main-repo import problem.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_FINANCE_REPORTER_PATH = _REPO_ROOT / "agents" / "finance_reporter.py"


def _load_finance_reporter():
    module_name = "agents.finance_reporter"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, _FINANCE_REPORTER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {_FINANCE_REPORTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def descriptors():
    FinanceReporter = _load_finance_reporter().FinanceReporter

    return {
        "report": FinanceReporter.report_descriptor(),
        "dashboard": FinanceReporter.dashboard_descriptor(),
    }


class TestFinanceReporterDescriptors:
    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_every_section_resolves_to_a_transformer(self, descriptors, key):
        """G-A: this is what makes publish_recipe return a recipe, not a GapReport."""
        for section in descriptors[key].sections:
            name = re.sub(r"\W+", "_", section.name).strip("_")
            transformer_registry.get(name)  # raises KeyError if unmapped

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_snapshot_col_passed_explicitly(self, descriptors, key):
        """Resolved question: explicit params, not the 'snapshot' default."""
        assert descriptors[key].params["snapshot_col"] == "snapshot_date"

    def test_report_layout_is_report_component(self, descriptors):
        assert descriptors["report"].layout.component == "Report"

    def test_dashboard_layout_is_infographic(self, descriptors):
        assert descriptors["dashboard"].layout.component == "Infographic"

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_layout_satisfies_catalog_required_keys(self, descriptors, key):
        props = descriptors[key].layout.properties
        assert "title" in props and "sections" in props

    def test_report_declares_narrative(self, descriptors):
        assert descriptors["report"].narrative.skill == "budget-narrative"

    def test_dashboard_declares_narrative(self, descriptors):
        assert descriptors["dashboard"].narrative.skill == "budget-narrative"

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_narrative_binds_are_optional(self, descriptors, key):
        """G-E: a no-narrator replay must not abort at the drift check."""

        def walk(v):
            if isinstance(v, dict):
                if "$bind" in v and "/narrative" in str(v["$bind"]):
                    assert v.get("optional") is True, f"non-optional narrative bind: {v}"
                for i in v.values():
                    walk(i)
            elif isinstance(v, list):
                for i in v:
                    walk(i)

        walk(descriptors[key].layout.properties)

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_narrative_facts_ordered_after_its_inputs(self, descriptors, key):
        names = [s.name for s in descriptors[key].sections]
        assert "narrative_facts" in names
        i = names.index("narrative_facts")
        for dep in ("variance_analysis", "top_movers", "division_breakdown"):
            assert names.index(dep) < i

    def test_distinct_recipe_names(self):
        FinanceReporter = _load_finance_reporter().FinanceReporter

        assert FinanceReporter.REPORT_RECIPE_NAME != FinanceReporter.DASHBOARD_RECIPE_NAME

    def test_no_handrolled_aggregation(self):
        """G-B: every number must come from a registered transformer."""
        src = _FINANCE_REPORTER_PATH.read_text()
        for banned in (
            "groupby",
            "itertuples",
            "_build_section_payload",
            "budget_variance_descriptor",
        ):
            assert banned not in src, f"{banned} should be gone"

    def test_narrative_mixin_composed_first(self):
        FinanceReporter = _load_finance_reporter().FinanceReporter
        from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin

        mro = FinanceReporter.__mro__
        assert mro.index(NarrativeMixin) < mro.index(InfographicAuthoringMixin)

    def test_narrative_facts_inputs_are_prior_step_output_keys(self, descriptors):
        """The generic narrative_facts shape (FEAT-420 Module 1): inputs are
        prior TransformStep output_keys, not raw dataset aliases."""
        report = descriptors["report"]
        section = next(s for s in report.sections if s.name == "narrative_facts")
        assert set(section.datasets) == {
            "variance_analysis",
            "top_movers",
            "division_breakdown",
        }

    @pytest.mark.asyncio
    async def test_skill_paths_discovers_the_real_budget_narrative_skill(self):
        """Code-review regression: `SkillRegistryMixin.skill_paths` defaults
        to `[]` (directory discovery is opt-in), and `NarrativeMixin` never
        sets it itself (criterion G-I: no domain wiring in the reusable
        mixin) — the COMPOSING agent must declare it, the same pattern as
        `agents/security_advisor.py`. Without `FinanceReporter.skill_paths`
        pointing at `.agent/skills/`, `narrate("budget-narrative")` would
        always return `None` in production, narrator or no narrator. This
        exercises the real `SkillsDirectoryLoader` against the real
        `skill_paths` class attribute — no test double for the registry.
        """
        from parrot.skills.loader import SkillsDirectoryLoader

        FinanceReporter = _load_finance_reporter().FinanceReporter
        assert FinanceReporter.skill_paths, "skill_paths must be non-empty"

        loader = SkillsDirectoryLoader(paths=FinanceReporter.skill_paths)
        discovered = await loader.discover()
        names = {skill.name for skill in discovered}
        assert "budget-narrative" in names, (
            f"budget-narrative not discovered via FinanceReporter.skill_paths "
            f"({FinanceReporter.skill_paths}); found: {names}"
        )


class TestFinanceReporterDatasetSQL:
    """`troc.finance_projection` is a `TableSource` — replay needs explicit SQL."""

    _REQUIRED_COLUMNS = (
        "snapshot_date",
        "division",
        "project",
        "rev_actual",
        "rev_budget",
        "ebitda_actual",
        "ebitda_budget",
    )

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_snapshots_dataset_declares_sql(self, descriptors, key):
        assert descriptors[key].dataset_sql.get("snapshots")

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_sql_selects_every_column_the_transformers_require(self, descriptors, key):
        sql = descriptors[key].dataset_sql["snapshots"]
        for column in self._REQUIRED_COLUMNS:
            assert column in sql, f"{column!r} missing from replay SQL"

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_sql_is_not_select_star(self, descriptors, key):
        """DatasetManager rejects a bare star on a TableSource."""
        sql = descriptors[key].dataset_sql["snapshots"]
        assert "*" not in sql.split("FROM")[0]

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_sql_targets_the_real_table_not_the_alias(self, descriptors, key):
        """TableSource.fetch() validates the statement against its own table."""
        sql = descriptors[key].dataset_sql["snapshots"]
        assert "troc.finance_projection" in sql

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_sql_declares_no_unresolvable_placeholders(self, descriptors, key):
        """The published recipes declare no params, so `{...}` would not resolve."""
        sql = descriptors[key].dataset_sql["snapshots"]
        assert "{" not in sql
