# Select Action Documentation

## Overview

The `Select` action allows you to select options from HTML `<select>` dropdown elements. It provides multiple selection methods (by value, visible text, or index) and automatically handles change/blur events.

## Action Definition

```python
class Select(BrowserAction):
    """Select an option from a dropdown/select element"""
    name: str = 'select'
    action: Literal['select'] = 'select'
    selector: str  # CSS selector for the select element
    value: Optional[str] = None  # Value attribute of option
    text: Optional[str] = None  # Visible text of option
    index: Optional[int] = None  # Zero-based index of option
    by: Literal['value', 'text', 'index'] = 'value'  # Selection method
    blur_after: bool = True  # Trigger blur/change events
    wait_after_select: Optional[str] = None  # Wait for element after select
    wait_timeout: int = 2  # Timeout for post-select wait
```

---

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `action` | `str` | ✅ | - | Must be `"select"` |
| `selector` | `str` | ✅ | - | CSS selector for the `<select>` element |
| `value` | `str` | Conditional | `None` | Value attribute of the option (required if `by='value'`) |
| `text` | `str` | Conditional | `None` | Visible text of the option (required if `by='text'`) |
| `index` | `int` | Conditional | `None` | Zero-based index of the option (required if `by='index'`) |
| `by` | `str` | ❌ | `'value'` | Selection method: `'value'`, `'text'`, or `'index'` |
| `blur_after` | `bool` | ❌ | `True` | Trigger blur and change events after selection |
| `wait_after_select` | `str` | ❌ | `None` | CSS selector to wait for after selecting |
| `wait_timeout` | `int` | ❌ | `2` | Timeout in seconds for post-select wait |
| `timeout` | `int` | ❌ | - | Maximum wait time for the select element |
| `description` | `str` | ❌ | - | Human-readable description |

---

## Selection Methods

### 1. By Value (Default)

Select an option by its `value` attribute:

```html
<select id="country">
    <option value="US">United States</option>
    <option value="CA">Canada</option>
    <option value="UK">United Kingdom</option>
</select>
```

```python
{
    "action": "select",
    "selector": "#country",
    "value": "CA",
    "by": "value",  # Optional, this is the default
    "description": "Select Canada"
}
```

### 2. By Text

Select an option by its visible text:

```html
<select id="state">
    <option value="ca">California</option>
    <option value="tx">Texas</option>
    <option value="ny">New York</option>
</select>
```

```python
{
    "action": "select",
    "selector": "#state",
    "text": "California",
    "by": "text",
    "description": "Select California by text"
}
```

### 3. By Index

Select an option by its position (0-based):

```html
<select id="size">
    <option>Small</option>
    <option>Medium</option>
    <option>Large</option>
</select>
```

```python
{
    "action": "select",
    "selector": "#size",
    "index": 2,  # Selects "Large" (third option)
    "by": "index",
    "description": "Select large size"
}
```

---

## blur_after Parameter

The `blur_after` parameter controls whether the element loses focus after selection, which triggers important events:

### When `blur_after=True` (Default)
- ✅ Triggers `change` event on the select element
- ✅ Triggers `blur` event (element loses focus)
- ✅ Activates dependent dropdowns (e.g., country → states)
- ✅ Runs JavaScript event listeners
- ✅ Updates form validation
- **Use Case**: Standard form behavior, cascading dropdowns

### When `blur_after=False`
- ❌ No events triggered automatically
- ❌ Element keeps focus
- **Use Case**: When you need to programmatically control event timing or avoid triggering unwanted behavior

```python
# Standard selection (recommended)
{
    "action": "select",
    "selector": "#country",
    "value": "US",
    "blur_after": True,  # Triggers events
    "description": "Select country and trigger dependent fields"
}

# Keep focus (rare)
{
    "action": "select",
    "selector": "#option",
    "value": "test",
    "blur_after": False,  # No events
    "description": "Select without triggering events"
}
```

---

## Waiting for Dynamic Content

Use `wait_after_select` for cascading dropdowns or AJAX-loaded content:

```python
# Select country and wait for states to load
{
    "action": "select",
    "selector": "#country",
    "value": "US",
    "wait_after_select": "#state option[value]:not([value=''])",
    "wait_timeout": 5,
    "description": "Select country and wait for states"
}
```

**HTML Example:**
```html
<select id="country">
    <option value="US">United States</option>
    <option value="CA">Canada</option>
</select>

<select id="state">
    <!-- Options loaded dynamically via AJAX -->
</select>
```

---

## Complete Examples

### Example 1: Simple Form

```python
steps = [
    {
        "action": "navigate",
        "url": "https://example.com/registration",
        "description": "Go to registration page"
    },
    {
        "action": "fill",
        "selector": "#email",
        "value": "user@example.com",
        "description": "Enter email"
    },
    {
        "action": "select",
        "selector": "#country",
        "value": "US",
        "description": "Select United States"
    },
    {
        "action": "click",
        "selector": "#submit",
        "description": "Submit form"
    }
]
```

### Example 2: Cascading Dropdowns

```python
steps = [
    {
        "action": "navigate",
        "url": "https://example.com/location",
        "description": "Go to location page"
    },
    {
        "action": "select",
        "selector": "#country",
        "value": "US",
        "wait_after_select": "#state",
        "wait_timeout": 5,
        "description": "Select country and wait for states"
    },
    {
        "action": "select",
        "selector": "#state",
        "text": "California",
        "by": "text",
        "wait_after_select": "#city",
        "wait_timeout": 3,
        "description": "Select state and wait for cities"
    },
    {
        "action": "select",
        "selector": "#city",
        "text": "Los Angeles",
        "by": "text",
        "description": "Select city"
    }
]
```

### Example 3: E-commerce Product Selection

```python
steps = [
    {
        "action": "navigate",
        "url": "https://shop.example.com/product/123",
        "description": "Go to product page"
    },
    {
        "action": "select",
        "selector": "#size",
        "text": "Large",
        "by": "text",
        "description": "Select size"
    },
    {
        "action": "select",
        "selector": "#color",
        "value": "blue",
        "description": "Select color"
    },
    {
        "action": "select",
        "selector": "#quantity",
        "index": 2,  # Select "3" if options are 1, 2, 3, 4...
        "by": "index",
        "description": "Select quantity"
    },
    {
        "action": "click",
        "selector": "#add-to-cart",
        "wait_after_click": ".cart-notification",
        "description": "Add to cart"
    }
]
```

### Example 4: Multi-step Form with Validation

```python
steps = [
    {
        "action": "navigate",
        "url": "https://example.com/survey",
        "description": "Go to survey"
    },
    {
        "action": "select",
        "selector": "#age-range",
        "value": "25-34",
        "wait_after_select": ".question-2",
        "description": "Select age range, wait for next question"
    },
    {
        "action": "select",
        "selector": "#education",
        "text": "Bachelor's Degree",
        "by": "text",
        "description": "Select education level"
    },
    {
        "action": "select",
        "selector": "#employment",
        "index": 1,
        "by": "index",
        "blur_after": True,
        "description": "Select employment status"
    }
]
```

---

## Comparison: Select vs Fill vs Evaluate

| Feature | Select | Fill | Evaluate |
|---------|--------|------|----------|
| **Use Case** | Dropdown menus | Text inputs | Custom JavaScript |
| **Target Element** | `<select>` | `<input>`, `<textarea>` | Any element |
| **Selection Methods** | value/text/index | N/A | Custom |
| **Auto Events** | change/blur | N/A | Manual |
| **Complexity** | Simple | Simple | Advanced |

**When to use Select:**
- ✅ Standard HTML `<select>` dropdowns
- ✅ Multi-option selections with known values
- ✅ Cascading/dependent dropdowns

**When to use Evaluate instead:**
- Custom dropdown implementations (not `<select>`)
- Complex selection logic
- Multiple selections in multi-select dropdowns

---

## Best Practices

### 1. **Prefer `by='value'`** (Default)
Values are more stable than visible text and faster than index:
```python
# ✅ Good - stable
{"action": "select", "selector": "#country", "value": "US"}

# ⚠️ Less stable - text might change with translations
{"action": "select", "selector": "#country", "text": "United States", "by": "text"}

# ❌ Fragile - breaks if options are reordered
{"action": "select", "selector": "#country", "index": 0, "by": "index"}
```

### 2. **Use `wait_after_select` for Dynamic Content**
Always wait for dependent elements to load:
```python
{
    "action": "select",
    "selector": "#country",
    "value": "US",
    "wait_after_select": "#state option:not([disabled])",  # Wait for enabled options
    "wait_timeout": 5
}
```

### 3. **Keep `blur_after=True` for Standard Behavior**
Unless you have a specific reason, always trigger events:
```python
# ✅ Standard - triggers all events
{"action": "select", "selector": "#field", "value": "option1", "blur_after": True}
```

### 4. **Combine with Wait Actions for Complex Pages**
```python
[
    {"action": "wait", "condition": "#country", "condition_type": "selector"},
    {"action": "select", "selector": "#country", "value": "US"},
    {"action": "wait", "duration": 1},  # Allow AJAX to complete
    {"action": "select", "selector": "#state", "text": "California", "by": "text"}
]
```

### 5. **Handle Errors Gracefully**
Check that options exist before selecting:
```python
{
    "action": "evaluate",
    "script": "return Array.from(document.querySelector('#country').options).map(o => o.value);",
    "description": "Log available options for debugging"
}
```

---

## Troubleshooting

### Issue: Selection doesn't trigger dependent dropdown

**Solution**: Ensure `blur_after=True` and use `wait_after_select`:
```python
{
    "action": "select",
    "selector": "#country",
    "value": "US",
    "blur_after": True,  # Must be True
    "wait_after_select": "#state",
    "wait_timeout": 5
}
```

### Issue: "Option not found" error

**Solution**: Verify the selection method and value:
```python
# Debug: Check available options first
{
    "action": "evaluate",
    "script": """
        const select = document.querySelector('#country');
        return Array.from(select.options).map(opt => ({
            value: opt.value,
            text: opt.text,
            index: opt.index
        }));
    """,
    "description": "List all options"
}
```

### Issue: Element not interactable

**Solution**: Wait for the select element to be ready:
```python
{
    "action": "wait",
    "condition": "#country",
    "condition_type": "selector",
    "timeout": 5
},
{
    "action": "select",
    "selector": "#country",
    "value": "US"
}
```

---

## Browser Support

| Browser | Selenium | Playwright |
|---------|----------|------------|
| Chrome | ✅ Full | ✅ Full |
| Firefox | ✅ Full | ✅ Full |
| Edge | ✅ Full | ✅ Full |
| Safari | ✅ Full | ✅ Full |
| Undetected Chrome | ✅ Full | N/A |

Both implementations use native driver methods for maximum reliability.
