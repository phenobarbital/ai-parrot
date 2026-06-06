---
id: F007
query_id: Q008
type: grep
intent: Determine whether an output-mode contract already exists and where it lives.
executed_at: 2026-06-05T13:11:00Z
duration_ms: 150
parent_id: null
depth: 0
---

# F007 — The `output_mode` contract already exists (on AIMessage + ask() kwarg)

## Summary

The semantic contract the brainstorm wants the router to *set* already exists.
`OutputMode` is a rich `str, Enum` (`models/outputs.py:37`) with `MAP`, `TABLE`,
`CHART`, `INFOGRAPHIC`, `STRUCTURED_CHART/TABLE/MAP`, etc. It is currently
threaded as an explicit **`ask(output_mode=...)` kwarg** and stored on the
**response/AIMessage** (`response.output_mode = ...`) — NOT on `RequestContext`.
`bots/data.py` even sets it heuristically today (e.g. `OutputMode.MAP`,
`OutputMode.INFOGRAPHIC`). So the brainstorm's assumption that `output_mode`
lives on the request carrier is incorrect: the carrier exists (F004) but the
mode lives on the ask() boundary + the response object.

## Citations

- path: `parrot/models/outputs.py`
  lines: 37-72
  symbol: `OutputMode`
  excerpt: |
    class OutputMode(str, Enum):
        DEFAULT = "default"
        CHART = "chart"
        MAP = "map"
        TABLE = "table"
        INFOGRAPHIC = "infographic"
        STRUCTURED_CHART = "structured_chart"
        STRUCTURED_TABLE = "structured_table"
        STRUCTURED_MAP = "structured_map"

- path: `parrot/bots/data.py`
  lines: 1294-1306
  symbol: `DataAgent.ask`
  excerpt: |
    async def ask(self, question: str, ...,
                  output_mode: Any = None,
                  format_kwargs: dict = None, ...) -> AIMessage:

- path: `parrot/bots/data.py`
  lines: 1091, 1801, 1857
  symbol: heuristic output_mode assignment
  excerpt: |
    response.output_mode = OutputMode.INFOGRAPHIC
    output_mode = OutputMode.MAP          # set inside data.py logic today
    response.output_mode = output_mode

- path: `parrot/bots/base.py`
  lines: 409, 1158, 1171
  symbol: `response.output_mode = output_mode`
  excerpt: |
    response.output_mode = output_mode    # response-level, not ctx-level

## Notes

Precedence today is implicitly "explicit ask(output_mode=) kwarg wins". A router
must therefore only fill `output_mode` when the caller left it `None` — matches
the brainstorm's §8.7 precedence requirement. Cross-ref F004, F006.
