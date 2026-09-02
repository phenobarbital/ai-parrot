"""RenderSpec.layout field + RecipeRunner (theme, layout) plumbing tests
(FEAT-493, TASK-2714)."""

from datetime import UTC, datetime

# Ensure the satellite's renderers self-register (interactive-html, ssr-html, pdf).
import parrot.outputs.a2ui_renderers.interactive_html
import parrot.outputs.a2ui_renderers.ssr_html  # noqa: F401
import pytest
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, LayoutSpec, RenderSpec
from parrot.outputs.a2ui.recipes.store import FileRecipeStore
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner
from pydantic import ValidationError


class TestRenderSpecLayout:
    def test_layout_field_accepted(self):
        assert RenderSpec(profile="interactive-html", layout="report").layout == "report"

    def test_layout_defaults_to_none(self):
        assert RenderSpec().layout is None

    def test_unknown_key_still_forbidden(self):
        with pytest.raises(ValidationError):
            RenderSpec(profile="interactive-html", palette="blue")


def _recipe(*, profile: str, theme: str | None = None, layout: str | None = None) -> InfographicRecipe:
    return InfographicRecipe(
        name="r",
        title="R",
        layout=LayoutSpec(component="Text", text="hi"),
        render=RenderSpec(profile=profile, theme=theme, layout=layout),
        updated_at=datetime.now(UTC),
    )


def _envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="s",
        catalogId="c",
        components=[Component(id="root", component="Text", text="hi")],
        dataModel={},
    )


@pytest.fixture
def runner(tmp_path) -> RecipeRunner:
    return RecipeRunner(FileRecipeStore(tmp_path), DatasetManager())


class TestRunnerPlumbing:
    pytestmark = pytest.mark.asyncio

    async def test_pair_reaches_html_renderer(self, runner):
        recipe = _recipe(profile="ssr_html", theme="dark", layout="report")
        artifact = await runner._render_or_raise(recipe, _envelope())
        doc = artifact.content.decode()
        assert 'data-theme="dark"' in doc
        assert 'data-layout="report"' in doc

    async def test_renderer_without_kwargs_unaffected(self, runner):
        """A renderer whose constructor accepts neither kwarg is still
        constructed and run exactly as before — no TypeError."""
        import parrot.outputs.a2ui_renderers.adaptive_cards  # noqa: F401

        recipe = _recipe(profile="adaptive_cards", theme="dark", layout="report")
        artifact = await runner._render_or_raise(recipe, _envelope())
        assert artifact is not None

    async def test_import_error_still_propagates_unchanged(self, runner):
        recipe = _recipe(profile="not-a-real-renderer-profile")
        with pytest.raises(ImportError):
            await runner._render_or_raise(recipe, _envelope())

    async def test_render_failure_still_stage_render(self, runner, monkeypatch):
        from parrot.outputs.a2ui_renderers import ssr_html as ssr_mod

        async def _boom(self, envelope, *, bake=True, deep_links=None):
            raise RuntimeError("boom")

        monkeypatch.setattr(ssr_mod.SSRHTMLRenderer, "render", _boom)
        recipe = _recipe(profile="ssr_html")
        with pytest.raises(RecipeRunException) as exc_info:
            await runner._render_or_raise(recipe, _envelope())
        assert exc_info.value.error.stage == "render"

    async def test_infographic_theme_prop_path_intact(self, runner):
        """`recipe.render.theme` still reaches `build_infographic` on the
        Infographic layout branch (unchanged by this task)."""
        recipe = InfographicRecipe(
            name="r2",
            title="R2",
            layout=LayoutSpec(component="Infographic", title="T", sections=[]),
            render=RenderSpec(profile="ssr_html", theme="dark"),
            updated_at=datetime.now(UTC),
        )
        envelope = runner._assemble_envelope_or_raise(recipe, {})
        infographic_comp = next(c for c in envelope.components if c.component == "Infographic")
        assert infographic_comp.model_extra.get("theme") == "dark"
