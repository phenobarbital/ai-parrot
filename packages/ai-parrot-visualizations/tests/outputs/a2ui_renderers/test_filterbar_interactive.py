"""Unit tests for the FilterBar interactive multiselect + client-side
dataModel filtering runtime (FEAT-493, TASK-2716).

interactive-html intercepts the ``filter-bar`` variant (a Row lowered by
``FilterBarComponent``, see ``catalog/parrot/filterbar.py``) and emits the
reference searchable-multiselect control, wiring it to a dependency-free
filtering runtime in ``_BEHAVIOR_JS`` that filters the already-embedded
``dataModel`` client-side — never a data re-fetch.
"""

import re

import pytest

pytest.importorskip("jsonpointer")

# Ensure the FilterBar catalog component self-registers.
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer

pytestmark = pytest.mark.asyncio


def _envelope(*components: Component, data_model=None) -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=list(components),
        dataModel=data_model or {},
    )


def _filterbar_and_table_envelope() -> CreateSurface:
    """A FilterBar over ``division`` alongside a DataTable bound to rows
    that carry that column — the case where a filter DOES apply."""
    return _envelope(
        Component(
            id="fb",
            component="FilterBar",
            filters=[
                {
                    "column": "division",
                    "label": "Division",
                    "options": [
                        {"label": "Sales", "value": "Sales"},
                        {"label": "Ops", "value": "Ops"},
                    ],
                    "multiple": True,
                },
            ],
        ),
        Component(
            id="tbl",
            component="DataTable",
            title="Ledger",
            columns=[{"name": "division", "title": "Division"}, {"name": "rev"}],
            data={"path": "/rows"},
        ),
        data_model={"rows": [{"division": "Sales", "rev": 100}, {"division": "Ops", "rev": 50}]},
    )


class TestFilterBarMarkup:
    async def test_multiselect_rendered(self):
        """Button, panel, search input, options, actions and reset all present."""
        art = await InteractiveHTMLRenderer().render(_filterbar_and_table_envelope())
        doc = art.content.decode()

        assert 'data-filterbar="filterbar-fb"' in doc
        assert "msf-btn" in doc  # toggle button
        assert "msf-panel" in doc  # dropdown panel
        assert "msf-search" in doc  # per-filter search input
        assert "msf-opt" in doc  # per-option checkbox row
        assert 'data-act="all"' in doc  # select-all
        assert 'data-act="none"' in doc  # clear
        assert "reset-btn" in doc  # global reset
        assert "Sales" in doc and "Ops" in doc  # option labels rendered

    async def test_filter_column_reaches_the_dom(self):
        """Each control carries its parrot_filter_column as a data attribute."""
        art = await InteractiveHTMLRenderer().render(_filterbar_and_table_envelope())
        doc = art.content.decode()

        assert 'data-filter-column="division"' in doc

    async def test_chips_and_summary_present(self):
        art = await InteractiveHTMLRenderer().render(_filterbar_and_table_envelope())
        doc = art.content.decode()

        assert re.search(r'data-filter-chips="filterbar-fb"', doc)
        assert re.search(r'data-filter-summary="filterbar-fb"', doc)
        assert "filter-summary" in doc

    async def test_untouched_section_still_renders_normally(self):
        """A component whose data does not carry the filter column renders
        unaffected — no filter markup leaks onto it."""
        env = _envelope(
            Component(
                id="fb",
                component="FilterBar",
                filters=[{"column": "division", "label": "Division", "options": []}],
            ),
            Component(id="k0", component="KPICard", label="Revenue", value=100),
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "Revenue" in doc


class TestFilteringRuntime:
    async def test_behaviour_js_references_filter_hooks(self):
        """The runtime is wired by data-* hook names, not by dashboard-specific ids."""
        art = await InteractiveHTMLRenderer().render(_filterbar_and_table_envelope())
        doc = art.content.decode()

        assert "[data-filterbar]" in doc
        assert "data-filter-column" in doc
        assert "data-filter-reset" in doc
        assert "data-filter-chips" in doc
        assert "data-filter-summary" in doc
        assert "data-msf-toggle" in doc
        assert "data-msf-search" in doc
        assert "table[data-table]" in doc

    async def test_no_external_references(self):
        """test_interactive_html.py:64-67's invariant, re-asserted with a FilterBar present."""
        art = await InteractiveHTMLRenderer().render(_filterbar_and_table_envelope())
        doc = art.content.decode()

        externals = re.findall(r'(?:src|href)="https?://[^"]+"', doc)
        assert externals == []
        assert "@import" not in doc
        assert "<script src=" not in doc
        assert "<link " not in doc

    async def test_table_rows_carry_raw_row_data_for_client_side_filtering(self):
        """Pre-rendered <tr> rows carry their raw row values so filtering
        toggles visibility instead of re-rendering from scratch."""
        art = await InteractiveHTMLRenderer().render(_filterbar_and_table_envelope())
        doc = art.content.decode()

        assert "data-row=" in doc
        assert "Sales" in doc and "Ops" in doc

    async def test_empty_result_notice_helper_wired(self):
        """The runtime carries an explicit no-rows-match notice path, not a
        bare empty canvas/table."""
        art = await InteractiveHTMLRenderer().render(_filterbar_and_table_envelope())
        doc = art.content.decode()

        assert "No rows match the current filters." in doc

    async def test_filtering_delegates_to_pagination_instead_of_fighting_it(self):
        """A table large enough to trigger TASK-2711's search/pagination
        registers itself in `tablePaginators`, and the FilterBar runtime
        (TASK-2716) looks it up before touching `<tr>.style.display`
        directly — regression guard: FilterBar's initial no-op
        `applyFilters()` call must not force every row's display back to
        "" and silently undo pagination's page-1-only visibility."""
        env = _envelope(
            Component(
                id="fb",
                component="FilterBar",
                filters=[{"column": "division", "label": "Division", "options": []}],
            ),
            Component(
                id="tbl",
                component="DataTable",
                title="Ledger",
                columns=[{"name": "division"}, {"name": "rev"}],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"division": "Sales", "rev": i} for i in range(101)]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "data-table-search" in doc  # pagination present (>100 rows)
        assert "tablePaginators" in doc  # the shared coordination registry
        assert "tablePaginators[tableId](rowPasses)" in doc
