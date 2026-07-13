# FEAT-273 — Legacy output-mode deprecations → A2UI

The A2UI rendering pipeline (`OutputMode.A2UI`, `parrot.outputs.a2ui`) supersedes the
ad-hoc legacy renderers. Per **G7 (coexist + deprecate)**, the legacy modes keep working
**unchanged** — but `parrot.outputs.formats.get_renderer(mode)` now emits a
`DeprecationWarning` for the replaced modes, naming the A2UI replacement. Removal is a
later feature.

## Deprecated modes → A2UI replacement

| Legacy `OutputMode` | A2UI replacement |
|---|---|
| `ALTAIR`, `PLOTLY`, `MATPLOTLIB`, `SEABORN`, `ECHARTS`, `STRUCTURED_CHART` | `OutputMode.A2UI` + **Chart** catalog component |
| `MAP`, `STRUCTURED_MAP` | `OutputMode.A2UI` + **Map** catalog component |
| `TABLE`, `STRUCTURED_TABLE` | `OutputMode.A2UI` + **DataTable** catalog component |
| `CARD` | `OutputMode.A2UI` + **Card** / **KPICard** catalog components |
| `TEMPLATE_REPORT`, `JINJA2` | `OutputMode.A2UI` + **Report** catalog component |
| `HTML`, `APPLICATION` | `OutputMode.A2UI` + **SSR-HTML** renderer |
| infographic **HTML** path (`get_infographic_html_renderer`) | `OutputMode.A2UI` + **Infographic** component + SSR-HTML renderer |

## Kept (NO warning)

`JSON`, `YAML`, `MARKDOWN`, `SLACK`, `WHATSAPP`, `TERMINAL`, `DEFAULT`, and the
infographic **JSON** path (`get_renderer(OutputMode.INFOGRAPHIC)`).

## Notes

- Warnings fire only at the single lazy-load choke point
  (`parrot.outputs.formats.get_renderer`) and the infographic-HTML seam — never in
  `bots/base.py`, `OutputFormatter`, or the handlers.
- Rendering output for every legacy mode is byte-identical to before; only warnings
  were added.
- Modes with no registered renderer (`CHART`, `INTERACTIVE`, `CODE`, `IMAGE`, …) are
  untouched and still raise `ValueError` from `get_renderer`.
