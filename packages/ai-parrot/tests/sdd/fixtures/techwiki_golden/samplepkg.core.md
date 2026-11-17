# samplepkg.core

Public fixture API.

## Class `PublicModel`

A public model used to exercise class rendering.

Fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` |  |  |
| `count` | `int` | `1` | How many times to repeat the name. |

Attributes:

| Attribute | Type | Description |
| --- | --- | --- |
| `label` | `str` | Return a readable label. |

### Class `PublicModel.Nested`

A nested public class.

## Class `Widget`

A sized widget.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `size` | `int` |  | Edge length in pixels. |
| `name` | `str \| None` | `None` | Optional display name. |

### Method `Widget.resize`

Change the widget size.

`resize(size: int) -> None`

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `size` | `int` |  | New edge length in pixels. |

Raises:

- `ValueError` — If ``size`` is not positive.

### Method `Widget.describe`

Return a one-line description.

`describe() -> str`

Returns: `str`

## Function `format_value`

Format a value.

Overloads:

- `format_value(value: int) -> str`
- `format_value(value: str) -> str`

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `value` | `int \| str` |  | The value to format. |

Returns: `str` — The formatted string.

## Function `make`

Build a widget.

`make(size: int, *, name: str | None = None) -> Widget`

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `size` | `int` |  | Edge length in pixels. |
| `name` | `str \| None` | `None` | Optional display name. |

Returns: `Widget` — The new widget.
