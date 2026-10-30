"""Flex ``kpi-table.md`` → recipe-sourced ``MetricDefinition`` importer (FEAT-756 M2)."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from parrot.metrics.models import (
    ChartShape,
    DataTableShape,
    DimensionSpec,
    KPICardShape,
    MapShape,
    MetricDefinition,
    PeriodBinding,
    RecipeSource,
    TimeSpec,
)

KPI_TABLE_HEADER = ["KPI", "Transformer", "Dataset alias(es)", "Recipe path", "Output mode", "Supported filters"]


class KpiTableRow(BaseModel):
    """One row of the Flex ``kpi-table.md`` table: kpi, transformer, dataset_aliases, recipe_path, output_mode, filters."""

    model_config = ConfigDict(extra="forbid")
    kpi: str
    transformer: str
    dataset_aliases: list[str]
    recipe_path: str
    output_mode: str
    filters: list[str]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _unquote(cell: str) -> str:
    return cell.replace("`", "").strip()


def _slugify(text: str) -> str:
    """Convert text to a valid metric ID slug."""
    # Convert to lowercase
    text = text.lower()
    # Replace non-alphanumeric characters with underscores
    text = re.sub(r"[^a-z0-9]+", "_", text)
    # Strip leading/trailing underscores
    text = text.strip("_")
    # Truncate to 63 characters
    text = text[:63]
    return text


def parse_kpi_table(markdown: str) -> list[KpiTableRow]:
    """Parse the 6-column GFM table (header ``| KPI | Transformer | Dataset alias(es) | Recipe path | Output mode | Supported filters |``)."""
    lines = markdown.split("\n")

    # Find the header line
    header_index = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|"):
            cells = _cells(line)
            if cells == KPI_TABLE_HEADER:
                header_index = i
                break

    if header_index is None:
        raise ValueError("KPI table header not found")

    # Skip the separator row (next line after header)
    data_start_index = header_index + 2

    # Parse data rows
    rows = []
    for i in range(data_start_index, len(lines)):
        line = lines[i].strip()
        if not line.startswith("|") or not line.endswith("|"):
            # Stop at the first non-table line
            break

        cells = _cells(line)
        if len(cells) != 6:
            continue

        # Parse the row
        kpi = cells[0]
        transformer = _unquote(cells[1])
        dataset_aliases = [_unquote(alias.strip()) for alias in cells[2].split(",")]
        recipe_path = _unquote(cells[3])
        output_mode = cells[4]  # Keep backticks for output mode
        filters = [f.strip() for f in cells[5].split(",")] if cells[5] else []

        row = KpiTableRow(
            kpi=kpi,
            transformer=transformer,
            dataset_aliases=dataset_aliases,
            recipe_path=recipe_path,
            output_mode=output_mode,
            filters=filters,
        )
        rows.append(row)

    return rows


def _shape_for(mode: str):
    """Map output mode to appropriate shape."""
    mode = mode.replace("`", "").strip()

    if mode == "KPICard hero":
        return KPICardShape(value_column="value", aggregate="none")
    elif mode == "STRUCTURED_CHART":
        return ChartShape(chart_type="line", x="month", y=["value"])
    elif mode == "STRUCTURED_TABLE":
        return DataTableShape(columns=[])
    elif mode == "STRUCTURED_MAP":
        return MapShape(lat="lat", lon="lon")
    else:
        raise ValueError(f"Unknown output mode: {mode}")


def import_kpi_table(
    markdown: str,
    *,
    recipe_name: str,
    recipe_owner: str | None,
    tenant: str | None,
    program: str | None = None,
    period_param: str = "month",
) -> list[MetricDefinition]:
    """Convert rows to ``RecipeSource`` definitions: ``KPICard hero`` → ``KPICardShape``, ``STRUCTURED_CHART`` →
    ``ChartShape(line)``, ``STRUCTURED_TABLE`` → ``DataTableShape``, ``STRUCTURED_MAP`` → ``MapShape``; the
    ``Supported filters`` cell becomes ``dimensions`` (minus the period filter, which becomes ``TimeSpec``)."""
    rows = parse_kpi_table(markdown)
    definitions = []

    for row in rows:
        # Create dimensions (filters minus period_param)
        dimension_filters = [f for f in row.filters if f != period_param]
        dimensions = [DimensionSpec(name=f.replace("_", " "), column=f) for f in dimension_filters]

        # Create time spec
        if period_param in row.filters:
            # Period filter is present, use placeholders
            time_spec = TimeSpec(binding=PeriodBinding(start_placeholder=period_param, end_placeholder=period_param))
        else:
            # Period filter is absent, use date column
            time_spec = TimeSpec(binding=PeriodBinding(date_column=period_param))

        # Create shape
        shape = _shape_for(row.output_mode)

        # Create description with lineage information
        description = (
            f"Imported from kpi-table.md; transformer={row.transformer}; datasets={', '.join(row.dataset_aliases)}"
        )

        # Handle special case for Proximity Staffing with {…} in recipe path
        data_model_path = row.recipe_path
        if "{store_layer,employee_layer,coverage}" in row.recipe_path:
            data_model_path = "/proximity_staffing/coverage"
            description += (
                "; Note: Original recipe path contains template variables {store_layer,employee_layer,coverage}"
            )

        # Create source
        source = RecipeSource(
            recipe_name=recipe_name,
            recipe_owner=recipe_owner,
            data_model_path=data_model_path,
            param_map={f: f for f in row.filters},
        )

        # Determine visibility
        visibility = "tenant" if tenant else "public"

        # Create metric definition
        definition = MetricDefinition(
            id=_slugify(row.kpi),
            name=row.kpi,
            tenant=tenant,
            program=program,
            description=description,
            aliases=[],
            dimensions=dimensions,
            time=time_spec,
            default_shape=shape,
            source=source,
            visibility=visibility,
        )

        definitions.append(definition)

    return definitions
