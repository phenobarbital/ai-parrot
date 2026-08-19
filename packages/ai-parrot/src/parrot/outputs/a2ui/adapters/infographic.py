"""``InfographicResponse`` → A2UI ``CreateSurface`` adapter (FEAT-273 Module 11 lane).

Bridges the legacy structured infographic model (:mod:`parrot.models.infographic`,
an ordered flat list of typed blocks) to the A2UI ``Infographic`` composite catalog
component (a header plus ordered *sections* nesting other catalog components).

The function is **pure and deterministic**: same input → byte-identical envelope.
No clocks, no uuids, no network, no LLM tokens (spec G2/D1a).

Sectioning policy
-----------------
``InfographicResponse.blocks`` is flat; the ``Infographic`` component is sectioned.
Blocks are grouped with these rules, applied in order:

* The **first** ``title`` block supplies the surface ``title``/``subtitle`` and does
  not open a section.
* Any **later** ``title`` block opens a new section (``heading`` = its title,
  ``text`` = its subtitle).
* A ``divider`` block closes the current section and opens an anonymous one.
* ``accordion`` and ``tab_view`` blocks flatten: each item/pane becomes its own
  sibling section (A2UI sections do not nest), with its nested blocks mapped as
  that section's components.
* Every other block maps to a nested catalog component appended to the current
  section. A ``summary`` becomes the section's ``text`` when that slot is still
  free, otherwise a ``Card``.

Block → component mapping
-------------------------
=================  =====================================================
Block              A2UI component
=================  =====================================================
``hero_card``      ``KPICard``
``chart``          ``Chart`` (+ rows into the data model, bound by pointer)
``table``          ``DataTable`` (+ rows into the data model)
``timeline``       ``Timeline``
``progress``       one ``KPICard`` per item
``summary``        section ``text``, else ``Card``
``bullet_list``    ``Card`` (items rendered into ``body``)
``checklist``      ``Card`` (items rendered into ``body``)
``callout``        ``Card`` (``badge`` carries the level)
``quote``          ``Card`` (``footer`` carries the attribution)
``image``          ``Card`` (``image`` + ``footer`` caption)
=================  =====================================================

Known lossy degradations (spec §8, OQ-C):

* Chart types with no A2UI equivalent (``radar``, ``heatmap``, ``treemap``,
  ``gauge``, ``funnel``, ``waterfall``, ``donut``) collapse to the nearest
  supported type — see :data:`CHART_TYPE_MAP`.
* Presentation-only fields (``layout``, ``color_by_sign``, per-series colors,
  table ``style``, bullet ``columns``…) are dropped: A2UI carries data and
  semantics, and the renderer owns presentation.
* ``Card`` ``title`` is omitted for blocks with no title-like field. The lowering
  in ``catalog/components/card.py`` skips absent properties, so this degrades to a
  title-less card rather than an invented heading.

One-way import rule (G8): this module imports only the a2ui core and the pure
Pydantic ``parrot.models.infographic`` module — never agents, clients or
DatasetManager.
"""

from __future__ import annotations

from typing import Any, Optional

from parrot.outputs.a2ui.builders import build_infographic
from parrot.outputs.a2ui.models import CreateSurface

__all__ = ["CHART_TYPE_MAP", "infographic_response_to_envelope"]


#: ``ChartType`` (legacy, 12 members) → A2UI ``Chart`` ``type`` enum
#: (``bar``/``line``/``area``/``scatter``/``pie``/``map``). Types with no direct
#: equivalent collapse to their nearest supported neighbour — a documented,
#: deterministic degradation, never a silent drop.
CHART_TYPE_MAP: dict[str, str] = {
    "bar": "bar",
    "line": "line",
    "area": "area",
    "scatter": "scatter",
    "pie": "pie",
    "donut": "pie",
    "radar": "line",
    "funnel": "bar",
    "waterfall": "bar",
    "heatmap": "bar",
    "treemap": "bar",
    "gauge": "bar",
}

_CHART_FALLBACK = "bar"

#: Maximum nesting depth followed when flattening ``accordion``/``tab_view``.
#: Beyond it, nested blocks degrade to a ``Card`` instead of recursing.
_MAX_NESTING_DEPTH = 4

_X_COLUMN = "label"


def _as_dict(value: Any) -> dict[str, Any]:
    """Return a plain dict view of a Pydantic model or mapping (never mutates)."""
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        return dumper(mode="json")
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(
        f"Expected an InfographicResponse, block model or mapping, got {type(value)!r}."
    )


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None`` values so absent optionals never reach the wire."""
    return {k: v for k, v in props.items() if v is not None}


def _descriptor(component: str, properties: dict[str, Any]) -> dict[str, Any]:
    """Build a nested composite child descriptor for the Infographic component."""
    return {"component": component, "properties": _clean(properties)}


def _unique(name: str, taken: dict[str, int]) -> str:
    """Return ``name`` made unique against ``taken`` (deterministic suffixing)."""
    count = taken.get(name, 0) + 1
    taken[name] = count
    return name if count == 1 else f"{name} ({count})"


def _lines(items: list[Any], *, ordered: bool = False) -> str:
    """Render list items as a deterministic text block for a ``Card`` body."""
    out: list[str] = []
    for index, item in enumerate(items, 1):
        text = item if isinstance(item, str) else str(item)
        out.append(f"{index}. {text}" if ordered else f"• {text}")
    return "\n".join(out)


def _text(value: Any) -> Optional[str]:
    """Flatten an ``I18nText`` value to a single string for A2UI properties.

    The A2UI envelope is single-language in v1: prefer the ``"en"`` key,
    else the first value in insertion order, else ``None``.

    Args:
        value: A plain ``str``, an ``I18nText`` mapping, or ``None``.

    Returns:
        A flat string, or ``None`` if ``value`` is ``None``.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        if "en" in value:
            return value["en"]
        return next(iter(value.values()), "")
    return str(value)


class _SectionAccumulator:
    """Collects sections while walking the flat block list.

    Sections are only materialised once they hold content, so a leading
    ``divider`` or a trailing boundary never emits an empty section.
    """

    def __init__(self) -> None:
        self._sections: list[dict[str, Any]] = []
        self._current: Optional[dict[str, Any]] = None

    def open(self, *, heading: Optional[str] = None, text: Optional[str] = None) -> None:
        """Close the current section and start a new one."""
        self.close()
        self._current = _clean({"heading": heading, "text": text})

    def close(self) -> None:
        """Flush the current section if it carries any content."""
        if self._current and (
            self._current.get("heading")
            or self._current.get("text")
            or self._current.get("components")
        ):
            self._sections.append(self._current)
        self._current = None

    def _ensure(self) -> dict[str, Any]:
        if self._current is None:
            self._current = {}
        return self._current

    def add(self, descriptor: dict[str, Any]) -> None:
        """Append a nested component descriptor to the current section."""
        section = self._ensure()
        section.setdefault("components", []).append(descriptor)

    def set_text(self, text: str) -> bool:
        """Fill the section's free ``text`` slot. Returns False when taken."""
        section = self._ensure()
        if section.get("text"):
            return False
        section["text"] = text
        return True

    def result(self) -> list[dict[str, Any]]:
        """Close the trailing section and return every collected section."""
        self.close()
        return self._sections


class _Converter:
    """Stateful walk over the block list, owning data-model key allocation."""

    def __init__(self) -> None:
        self.data_model: dict[str, dict[str, Any]] = {}
        self._chart_index = 0
        self._table_index = 0

    # -- data model -----------------------------------------------------

    def _bind_rows(self, bucket: str, key: str, rows: list[dict[str, Any]]) -> dict[str, str]:
        self.data_model.setdefault(bucket, {})[key] = rows
        return {"$bind": f"/{bucket}/{key}"}

    # -- per-block mappings ---------------------------------------------

    def _chart(self, block: dict[str, Any]) -> dict[str, Any]:
        key = f"chart-{self._chart_index}"
        self._chart_index += 1

        labels = block.get("labels") or []
        series = block.get("series") or []

        # Reserve the x column name so a series called "label" is suffixed
        # instead of overwriting the category column.
        taken: dict[str, int] = {_X_COLUMN: 1}
        y_names = [_unique(str(s.get("name") or "series"), taken) for s in series]

        rows: list[dict[str, Any]] = []
        for i, label in enumerate(labels):
            row: dict[str, Any] = {_X_COLUMN: label}
            for name, spec in zip(y_names, series):
                values = spec.get("values") or []
                row[name] = values[i] if i < len(values) else None
            rows.append(row)

        raw_type = str(block.get("chart_type") or "")
        properties = {
            "title": block.get("title"),
            "type": CHART_TYPE_MAP.get(raw_type, _CHART_FALLBACK),
            "x": _X_COLUMN,
            "y": y_names,
            "stacked": bool(block.get("stacked")),
            "showLegend": block.get("show_legend") is not False,
            "data": self._bind_rows("charts", key, rows),
        }
        return _descriptor("Chart", properties)

    def _table(self, block: dict[str, Any]) -> dict[str, Any]:
        key = f"table-{self._table_index}"
        self._table_index += 1

        taken: dict[str, int] = {}
        names: list[str] = []
        for column in block.get("columns") or []:
            header = column if isinstance(column, str) else str(_as_dict(column).get("header") or "")
            names.append(_unique(header or "column", taken))

        rows: list[dict[str, Any]] = []
        for raw_row in block.get("rows") or []:
            cells = list(raw_row) if isinstance(raw_row, (list, tuple)) else [raw_row]
            rows.append(
                {name: (cells[i] if i < len(cells) else None) for i, name in enumerate(names)}
            )

        properties = {
            "title": block.get("title") or block.get("caption"),
            "columns": [{"name": name, "title": name} for name in names],
            "totalRows": len(rows),
            "data": self._bind_rows("tables", key, rows),
        }
        return _descriptor("DataTable", properties)

    def _hero_card(self, block: dict[str, Any]) -> dict[str, Any]:
        return _descriptor(
            "KPICard",
            {
                "label": block.get("label") or "",
                "value": block.get("value") or "",
                "delta": block.get("trend_value"),
                "trend": block.get("trend"),
            },
        )

    def _timeline(self, block: dict[str, Any]) -> dict[str, Any]:
        events = []
        for raw in block.get("events") or []:
            event = _as_dict(raw)
            events.append(
                _clean(
                    {
                        "timestamp": event.get("date"),
                        "title": event.get("title") or "",
                        "description": event.get("description"),
                    }
                )
            )
        return _descriptor("Timeline", {"title": block.get("title"), "events": events})

    def _progress(self, block: dict[str, Any]) -> list[dict[str, Any]]:
        descriptors = []
        for raw in block.get("items") or []:
            item = _as_dict(raw)
            descriptors.append(
                _descriptor(
                    "KPICard",
                    {"label": item.get("label") or "", "value": item.get("value")},
                )
            )
        return descriptors

    def _card_like(self, block: dict[str, Any], block_type: str) -> dict[str, Any]:
        """Map the block types that share the generic ``Card`` shape."""
        if block_type == "bullet_list":
            return _descriptor(
                "Card",
                {
                    "title": block.get("title"),
                    "body": _lines(
                        block.get("items") or [], ordered=bool(block.get("ordered"))
                    ),
                },
            )
        if block_type == "checklist":
            lines = []
            for raw in block.get("items") or []:
                item = _as_dict(raw)
                mark = "[x]" if item.get("checked") else "[ ]"
                lines.append(f"{mark} {item.get('text') or ''}".rstrip())
            return _descriptor(
                "Card", {"title": block.get("title"), "body": "\n".join(lines)}
            )
        if block_type == "callout":
            return _descriptor(
                "Card",
                {
                    "title": block.get("title"),
                    "body": block.get("content") or "",
                    "badge": block.get("level"),
                },
            )
        if block_type == "quote":
            attribution = " — ".join(
                part for part in (block.get("author"), block.get("source")) if part
            )
            return _descriptor(
                "Card",
                {"body": block.get("text") or "", "footer": attribution or None},
            )
        if block_type == "image":
            return _descriptor(
                "Card",
                {
                    "title": block.get("alt"),
                    "image": block.get("url"),
                    "footer": block.get("caption"),
                },
            )
        # summary (title present or text slot taken) and any unknown block type
        return _descriptor(
            "Card",
            {
                "title": block.get("title"),
                "body": block.get("content") or block.get("text") or "",
            },
        )

    def _chain(self, block: dict[str, Any]) -> dict[str, Any]:
        """Map a ``chain`` block to a ``Card`` with an arrow-joined node body."""
        nodes = [_as_dict(raw) for raw in block.get("nodes") or []]
        labels = [_text(node.get("label")) or "" for node in nodes]
        subtitle = "vertical" if block.get("direction") == "vertical" else None
        return _descriptor(
            "Card",
            {
                "title": _text(block.get("title")),
                "subtitle": subtitle,
                "body": " → ".join(labels),
            },
        )

    def _steps(self, block: dict[str, Any]) -> dict[str, Any]:
        """Map a ``steps`` block to a ``Card`` with a numbered step body."""
        lines = []
        for raw in block.get("steps") or []:
            step = _as_dict(raw)
            label = _text(step.get("label")) or ""
            description = _text(step.get("description"))
            lines.append(f"{label} — {description}" if description else label)
        return _descriptor(
            "Card",
            {
                "title": _text(block.get("title")),
                "body": _lines(lines, ordered=True),
            },
        )

    def _code(self, block: dict[str, Any]) -> dict[str, Any]:
        """Map a ``code`` block to a ``Card`` with the code as body, badge=language."""
        return _descriptor(
            "Card",
            {
                "title": _text(block.get("title")),
                "body": block.get("code") or "",
                "badge": block.get("language"),
            },
        )

    def _card_grid(self, block: dict[str, Any]) -> list[dict[str, Any]]:
        """Map a ``card_grid`` block to one ``Card`` descriptor per grid card."""
        descriptors = []
        for raw in block.get("cards") or []:
            card = _as_dict(raw)
            descriptors.append(
                _descriptor(
                    "Card",
                    {
                        "title": _text(card.get("title")),
                        "body": _text(card.get("body")),
                    },
                )
            )
        return descriptors

    # -- walk ------------------------------------------------------------

    def walk(
        self,
        blocks: list[Any],
        sections: _SectionAccumulator,
        *,
        depth: int = 0,
        seen_title: bool = False,
    ) -> tuple[Optional[str], Optional[str], bool]:
        """Map ``blocks`` into ``sections``.

        Returns the surface ``(title, subtitle, seen_title)`` harvested from the
        first ``title`` block encountered.
        """
        title: Optional[str] = None
        subtitle: Optional[str] = None

        for raw in blocks:
            block = _as_dict(raw)
            block_type = str(block.get("type") or "")

            if block_type == "title":
                if not seen_title:
                    title = block.get("title")
                    subtitle = block.get("subtitle")
                    seen_title = True
                else:
                    sections.open(
                        heading=block.get("title"), text=block.get("subtitle")
                    )
                continue

            if block_type == "divider":
                sections.open()
                continue

            if block_type in ("accordion", "tab_view") and depth < _MAX_NESTING_DEPTH:
                self._flatten_container(block, block_type, sections, depth)
                continue

            if block_type == "summary" and not block.get("title"):
                if sections.set_text(block.get("content") or ""):
                    continue

            if block_type == "chart":
                sections.add(self._chart(block))
            elif block_type == "table":
                sections.add(self._table(block))
            elif block_type == "hero_card":
                sections.add(self._hero_card(block))
            elif block_type == "timeline":
                sections.add(self._timeline(block))
            elif block_type == "progress":
                for descriptor in self._progress(block):
                    sections.add(descriptor)
            elif block_type == "chain":
                sections.add(self._chain(block))
            elif block_type == "steps":
                sections.add(self._steps(block))
            elif block_type == "code":
                sections.add(self._code(block))
            elif block_type == "card_grid":
                for descriptor in self._card_grid(block):
                    sections.add(descriptor)
            else:
                sections.add(self._card_like(block, block_type))

        return title, subtitle, seen_title

    def _flatten_container(
        self,
        block: dict[str, Any],
        block_type: str,
        sections: _SectionAccumulator,
        depth: int,
    ) -> None:
        """Flatten an accordion/tab_view into sibling sections (sections never nest)."""
        if block_type == "accordion":
            entries = [
                (_as_dict(item).get("title"), _as_dict(item).get("content_blocks") or [])
                for item in block.get("items") or []
            ]
        else:
            entries = [
                (_as_dict(pane).get("label"), _as_dict(pane).get("blocks") or [])
                for pane in block.get("tabs") or []
            ]

        group_title = block.get("title")
        for index, (heading, nested) in enumerate(entries):
            # The group title only labels the first sub-section, so the grouping
            # survives flattening without repeating on every sibling.
            if group_title and index == 0 and heading:
                heading = f"{group_title} — {heading}"
            elif group_title and index == 0:
                heading = group_title
            sections.open(heading=heading)
            self.walk(nested, sections, depth=depth + 1, seen_title=True)


def infographic_response_to_envelope(
    response: Any,
    *,
    surface_id: str = "infographic",
    title: Optional[str] = None,
    theme: Optional[str] = None,
) -> CreateSurface:
    """Convert an ``InfographicResponse`` into a validated A2UI ``CreateSurface``.

    Pure and deterministic — the same response always yields an identical envelope.

    Args:
        response: An :class:`~parrot.models.infographic.InfographicResponse`, or any
            mapping with the same shape (``blocks``/``theme``/``template``).
        surface_id: Surface id for the emitted envelope.
        title: Explicit surface title. When omitted, the first ``title`` block's
            title is used, falling back to the response ``template`` and finally
            to ``"Infographic"``.
        theme: Explicit theme hint. When omitted, ``response.theme`` is used.

    Returns:
        A catalog-validated ``CreateSurface`` carrying one ``Infographic`` component,
        with chart and table rows resolved through data-model bindings.

    Raises:
        TypeError: If ``response`` is neither a model nor a mapping.
        CatalogValidationError: If any mapped component is not in the catalog.
    """
    payload = _as_dict(response)
    blocks = payload.get("blocks") or []

    sections = _SectionAccumulator()
    converter = _Converter()
    block_title, subtitle, _ = converter.walk(blocks, sections)

    return build_infographic(
        title=title or block_title or payload.get("template") or "Infographic",
        subtitle=subtitle,
        sections=sections.result(),
        theme=theme if theme is not None else payload.get("theme"),
        surface_id=surface_id,
        data_model=converter.data_model or None,
    )
