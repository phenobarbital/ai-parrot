# WebScrapingTool Documentation

## Overview

WebScrapingTool is an advanced web scraping and browser automation component of AI-Parrot that provides LLM integration support for automated web interactions.

### Key Features

- **Dual Driver Support**: Works with both Selenium and Playwright
- **Step-by-step Navigation**: Declarative action-based workflow
- **Flexible Content Extraction**: Multiple extraction methods
- **Error Handling**: Built-in retry logic and error management
- **Mobile Emulation**: Support for mobile device simulation
- **Authentication**: HTTP and cookie-based authentication
- **File Operations**: Upload and download monitoring

### Driver Support

- **Selenium**: Chrome, Firefox, Edge, Safari, Undetected Chrome
- **Playwright**: Chrome, Firefox, WebKit

---

## Configuration

### Initialization Parameters

```python
from aiparrot.tools import WebScrapingTool

tool = WebScrapingTool(
    browser='chrome',                    # Browser type: 'chrome', 'firefox', 'edge', 'safari', 'undetected'
    driver_type='selenium',              # Driver: 'selenium' or 'playwright'
    headless=True,                       # Run in headless mode
    mobile=False,                        # Enable mobile emulation
    mobile_device='iPhone 14 Pro Max',   # Specific mobile device
    browser_binary=None,                 # Custom browser path
    driver_binary=None,                  # Custom driver path
    auto_install=True,                   # Auto-install driver
    default_timeout=10,                  # Default timeout (seconds)
    retry_attempts=3,                    # Retry attempts for actions
    delay_between_actions=1,             # Delay between actions (seconds)
    overlay_housekeeping=True            # Automatic overlay handling
)
```

---

## Available Actions

### Navigation Actions

#### 1. Navigate

Navigate to a specific URL.

**Parameters:**
- `action`: `"navigate"` (required)
- `url`: Target URL (required)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "navigate",
    "url": "https://example.com",
    "timeout": 10,
    "description": "Navigate to example homepage"
}
```

#### 2. Back

Navigate back in browser history.

**Parameters:**
- `action`: `"back"` (required)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "back",
    "description": "Go back to previous page"
}
```

#### 3. Refresh

Refresh the current page.

**Parameters:**
- `action`: `"refresh"` (required)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "refresh",
    "description": "Reload the current page"
}
```

---

### Interaction Actions

#### 4. Click

Click on a web page element.

**Parameters:**
- `action`: `"click"` (required)
- `selector`: CSS/XPath selector (required)
- `selector_type`: Selector type: `"css"`, `"xpath"`, or `"text"` (default: `"css"`)
- `click_type`: Click type: `"single"`, `"double"`, or `"right"` (default: `"single"`)
- `wait_after_click`: CSS selector to wait for after clicking (optional)
- `wait_timeout`: Timeout for post-click wait in seconds (default: 2)
- `no_wait`: Skip waiting after click (default: False)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Basic click
{
    "action": "click",
    "selector": "#submit-button",
    "description": "Click submit button"
}

# Click with XPath
{
    "action": "click",
    "selector": "//button[@type='submit']",
    "selector_type": "xpath",
    "description": "Click submit using XPath"
}

# Click by text content
{
    "action": "click",
    "selector": "Sign In",
    "selector_type": "text",
    "description": "Click sign in link"
}

# Double click
{
    "action": "click",
    "selector": ".item",
    "click_type": "double",
    "description": "Double click item"
}

# Wait for element after clicking
{
    "action": "click",
    "selector": "#load-more",
    "wait_after_click": ".new-content",
    "wait_timeout": 5,
    "description": "Click load more and wait for content"
}
```

#### 5. Fill

Fill text into an input field.

**Parameters:**
- `action`: `"fill"` (required)
- `selector`: CSS selector for input field (required)
- `value`: Text to enter (required)
- `clear_first`: Clear existing content before filling (default: True)
- `press_enter`: Press Enter after filling (default: False)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Basic fill
{
    "action": "fill",
    "selector": "#username",
    "value": "user@example.com",
    "description": "Enter username"
}

# Fill and submit with Enter
{
    "action": "fill",
    "selector": "#search-box",
    "value": "Python tutorials",
    "press_enter": True,
    "description": "Search for Python tutorials"
}

# Fill without clearing
{
    "action": "fill",
    "selector": "#notes",
    "value": " - Additional note",
    "clear_first": False,
    "description": "Append to notes"
}
```

#### 6. PressKey

Press keyboard keys.

**Parameters:**
- `action`: `"press_key"` (required)
- `key`: Key to press: `"enter"`, `"tab"`, `"escape"`, `"space"`, `"arrow_up"`, `"arrow_down"`, `"arrow_left"`, `"arrow_right"` (required)
- `selector`: CSS selector to focus before pressing (optional)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Press Enter
{
    "action": "press_key",
    "key": "enter",
    "description": "Submit form with Enter"
}

# Press Tab on specific element
{
    "action": "press_key",
    "key": "tab",
    "selector": "#first-field",
    "description": "Tab to next field"
}

# Press Escape
{
    "action": "press_key",
    "key": "escape",
    "description": "Close modal"
}
```

#### 7. Scroll

Scroll the page or a specific element.

**Parameters:**
- `action`: `"scroll"` (required)
- `direction`: Scroll direction: `"up"`, `"down"`, `"top"`, `"bottom"` (default: `"down"`)
- `amount`: Scroll amount in pixels (default: 500)
- `selector`: CSS selector of element to scroll (optional, scrolls page if not provided)
- `smooth`: Use smooth scrolling (default: False)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Scroll down page
{
    "action": "scroll",
    "direction": "down",
    "amount": 1000,
    "description": "Scroll down 1000px"
}

# Scroll to bottom
{
    "action": "scroll",
    "direction": "bottom",
    "description": "Scroll to page bottom"
}

# Scroll specific element
{
    "action": "scroll",
    "selector": "#scrollable-div",
    "direction": "down",
    "amount": 300,
    "description": "Scroll container"
}

# Smooth scroll
{
    "action": "scroll",
    "direction": "top",
    "smooth": True,
    "description": "Smooth scroll to top"
}
```

---

### Data Extraction Actions

#### 8. GetText

Extract text content from elements.

**Parameters:**
- `action`: `"get_text"` (required)
- `selector`: CSS selector for elements (required)
- `extract_type`: Extraction type: `"text"`, `"attribute"`, `"html"` (default: `"text"`)
- `attribute`: Attribute name if extract_type is `"attribute"` (optional)
- `multiple`: Extract from multiple elements (default: False)
- `wait_for`: Wait for element to appear (default: True)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Extract text from single element
{
    "action": "get_text",
    "selector": "h1.title",
    "description": "Get page title"
}

# Extract from multiple elements
{
    "action": "get_text",
    "selector": ".product-name",
    "multiple": True,
    "description": "Get all product names"
}

# Extract attribute
{
    "action": "get_text",
    "selector": "a.download-link",
    "extract_type": "attribute",
    "attribute": "href",
    "description": "Get download URL"
}

# Extract HTML content
{
    "action": "get_text",
    "selector": ".article-content",
    "extract_type": "html",
    "description": "Get article HTML"
}
```

#### 9. GetHTML

Get the complete page HTML.

**Parameters:**
- `action`: `"get_html"` (required)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "get_html",
    "description": "Get full page HTML"
}
```

---

### Cookie Management

#### 10. GetCookies

Retrieve browser cookies.

**Parameters:**
- `action`: `"get_cookies"` (required)
- `domain`: Filter cookies by domain (optional)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Get all cookies
{
    "action": "get_cookies",
    "description": "Get all cookies"
}

# Get cookies for specific domain
{
    "action": "get_cookies",
    "domain": "example.com",
    "description": "Get example.com cookies"
}
```

#### 11. SetCookies

Set browser cookies.

**Parameters:**
- `action`: `"set_cookies"` (required)
- `cookies`: List of cookie dictionaries (required)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "set_cookies",
    "cookies": [
        {
            "name": "session_id",
            "value": "abc123",
            "domain": "example.com",
            "path": "/",
            "secure": True
        },
        {
            "name": "user_pref",
            "value": "dark_mode",
            "domain": "example.com"
        }
    ],
    "description": "Set authentication cookies"
}
```

---

### Authentication

#### 12. Authenticate

Perform HTTP authentication.

**Parameters:**
- `action`: `"authenticate"` (required)
- `username`: Username for authentication (required)
- `password`: Password for authentication (required)
- `auth_type`: Authentication type: `"basic"`, `"digest"`, `"ntlm"` (default: `"basic"`)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "authenticate",
    "username": "admin",
    "password": "secret123",
    "auth_type": "basic",
    "description": "HTTP Basic Auth"
}
```

---

### Waiting Actions

#### 13. Wait

Wait for a specified duration or condition.

**Parameters:**
- `action`: `"wait"` (required)
- `duration`: Wait duration in seconds (optional)
- `condition`: Wait condition: `"element"`, `"element_visible"`, `"element_hidden"`, `"url_contains"`, `"title_contains"` (optional)
- `selector`: CSS selector for element conditions (optional)
- `value`: Value for URL/title conditions (optional)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Wait for duration
{
    "action": "wait",
    "duration": 3,
    "description": "Wait 3 seconds"
}

# Wait for element
{
    "action": "wait",
    "condition": "element",
    "selector": ".loading-complete",
    "timeout": 10,
    "description": "Wait for loading to complete"
}

# Wait for element to be visible
{
    "action": "wait",
    "condition": "element_visible",
    "selector": "#content",
    "timeout": 5,
    "description": "Wait for content to appear"
}

# Wait for URL change
{
    "action": "wait",
    "condition": "url_contains",
    "value": "dashboard",
    "timeout": 10,
    "description": "Wait for redirect to dashboard"
}
```

#### 14. AwaitHuman

Pause for human intervention with optional message display.

**Parameters:**
- `action`: `"await_human"` (required)
- `message`: Message to display (optional)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "await_human",
    "message": "Please complete the CAPTCHA and press Enter to continue",
    "timeout": 300,
    "description": "Wait for CAPTCHA resolution"
}
```

#### 15. AwaitKeyPress

Wait for a specific keyboard input.

**Parameters:**
- `action`: `"await_keypress"` (required)
- `expected_key`: Key to wait for (default: `"enter"`)
- `message`: Message to display (optional)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "await_keypress",
    "expected_key": "enter",
    "message": "Review the data and press Enter to continue",
    "description": "Wait for user confirmation"
}
```

#### 16. AwaitBrowserEvent

Wait for specific browser events.

**Parameters:**
- `action`: `"await_browser_event"` (required)
- `event_type`: Event type: `"load"`, `"domcontentloaded"`, `"networkidle"`, `"popup"`, `"dialog"` (required)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Wait for page load
{
    "action": "await_browser_event",
    "event_type": "load",
    "timeout": 30,
    "description": "Wait for page fully loaded"
}

# Wait for network idle
{
    "action": "await_browser_event",
    "event_type": "networkidle",
    "timeout": 10,
    "description": "Wait for AJAX requests to complete"
}
```

---

### File Operations

#### 17. Screenshot

Capture a screenshot.

**Parameters:**
- `action`: `"screenshot"` (required)
- `filepath`: Path to save screenshot (required)
- `full_page`: Capture full page (default: False)
- `selector`: CSS selector to capture specific element (optional)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Screenshot viewport
{
    "action": "screenshot",
    "filepath": "./screenshots/page.png",
    "description": "Capture viewport"
}

# Full page screenshot
{
    "action": "screenshot",
    "filepath": "./screenshots/full_page.png",
    "full_page": True,
    "description": "Capture full page"
}

# Element screenshot
{
    "action": "screenshot",
    "filepath": "./screenshots/element.png",
    "selector": "#main-content",
    "description": "Capture specific element"
}
```

#### 18. UploadFile

Upload a file to an input field.

**Parameters:**
- `action`: `"upload_file"` (required)
- `selector`: CSS selector for file input (required)
- `filepath`: Path to file to upload (required)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "upload_file",
    "selector": "input[type='file']",
    "filepath": "./documents/resume.pdf",
    "description": "Upload resume"
}
```

#### 19. WaitForDownload

Monitor and wait for file download completion.

**Parameters:**
- `action`: `"wait_for_download"` (required)
- `download_dir`: Directory to monitor for downloads (required)
- `expected_filename`: Expected filename pattern (optional)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Example:**

```python
{
    "action": "wait_for_download",
    "download_dir": "./downloads",
    "expected_filename": "report_*.pdf",
    "timeout": 60,
    "description": "Wait for report download"
}
```

---

### Advanced Actions

#### 20. Evaluate

Execute JavaScript code in the browser context.

**Parameters:**
- `action`: `"evaluate"` (required)
- `script`: JavaScript code to execute (required)
- `args`: Arguments to pass to the script (optional)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Simple evaluation
{
    "action": "evaluate",
    "script": "return document.title;",
    "description": "Get page title via JS"
}

# Complex evaluation with arguments
{
    "action": "evaluate",
    "script": "return arguments[0] + arguments[1];",
    "args": [5, 10],
    "description": "Calculate sum"
}

# Modify page content
{
    "action": "evaluate",
    "script": "document.querySelector('#banner').style.display = 'none';",
    "description": "Hide banner"
}
```

#### 21. Loop

Execute a sequence of actions repeatedly.

**Parameters:**
- `action`: `"loop"` (required)
- `actions`: List of actions to execute in loop (required)
- `iterations`: Number of iterations (optional, use with values or condition)
- `condition`: JavaScript condition to continue looping (optional)
- `values`: List of values to iterate over (optional)
- `value_name`: Variable name for current value (default: `"value"`)
- `break_on_error`: Stop loop on error (default: True)
- `max_iterations`: Safety limit (default: 100)
- `start_index`: Starting index (default: 0)
- `do_replace`: Replace `{{index}}` and `{{index_1}}` in parameters (default: True)
- `timeout`: Maximum wait time in seconds (optional)
- `description`: Human-readable description (optional)

**Examples:**

```python
# Fixed iteration loop
{
    "action": "loop",
    "iterations": 5,
    "actions": [
        {
            "action": "click",
            "selector": ".load-more"
        },
        {
            "action": "wait",
            "duration": 2
        }
    ],
    "description": "Load more content 5 times"
}

# Condition-based loop
{
    "action": "loop",
    "condition": "document.querySelector('.next-page') !== null",
    "actions": [
        {
            "action": "click",
            "selector": ".next-page"
        },
        {
            "action": "wait",
            "condition": "element",
            "selector": ".content-loaded"
        }
    ],
    "max_iterations": 20,
    "description": "Navigate through all pages"
}

# Value iteration with index replacement
{
    "action": "loop",
    "values": ["apple", "banana", "cherry"],
    "value_name": "fruit",
    "actions": [
        {
            "action": "fill",
            "selector": "#search-{{index}}",
            "value": "{{fruit}}"
        },
        {
            "action": "click",
            "selector": "#submit-{{index_1}}"
        }
    ],
    "description": "Search for each fruit"
}
```

---

## Complete Usage Examples

### Example 1: Basic Login Flow

```python
from aiparrot.tools import WebScrapingTool

tool = WebScrapingTool(browser='chrome', headless=False)

steps = [
    {
        "action": "navigate",
        "url": "https://example.com/login",
        "description": "Go to login page"
    },
    {
        "action": "fill",
        "selector": "#username",
        "value": "user@example.com",
        "description": "Enter username"
    },
    {
        "action": "fill",
        "selector": "#password",
        "value": "secret123",
        "description": "Enter password"
    },
    {
        "action": "click",
        "selector": "#login-button",
        "wait_after_click": ".dashboard",
        "description": "Click login and wait for dashboard"
    }
]

result = await tool.execute(steps=steps)
```

### Example 2: E-commerce Product Scraping

```python
steps = [
    {
        "action": "navigate",
        "url": "https://shop.example.com/products",
        "description": "Navigate to products page"
    },
    {
        "action": "wait",
        "condition": "element",
        "selector": ".product-list",
        "description": "Wait for products to load"
    },
    {
        "action": "loop",
        "iterations": 3,
        "actions": [
            {
                "action": "scroll",
                "direction": "down",
                "amount": 1000
            },
            {
                "action": "wait",
                "duration": 2
            }
        ],
        "description": "Scroll to load more products"
    },
    {
        "action": "get_text",
        "selector": ".product-name",
        "multiple": True,
        "description": "Extract all product names"
    },
    {
        "action": "get_text",
        "selector": ".product-price",
        "multiple": True,
        "description": "Extract all prices"
    }
]

selectors = [
    {
        "name": "products",
        "selector": ".product-card",
        "extract_type": "html",
        "multiple": True
    }
]

result = await tool.execute(steps=steps, selectors=selectors)
```

### Example 3: Form Automation with File Upload

```python
steps = [
    {
        "action": "navigate",
        "url": "https://example.com/application",
        "description": "Go to application form"
    },
    {
        "action": "fill",
        "selector": "#name",
        "value": "John Doe",
        "description": "Enter name"
    },
    {
        "action": "fill",
        "selector": "#email",
        "value": "john@example.com",
        "description": "Enter email"
    },
    {
        "action": "upload_file",
        "selector": "input[type='file']",
        "filepath": "./documents/cv.pdf",
        "description": "Upload CV"
    },
    {
        "action": "click",
        "selector": "#submit",
        "description": "Submit form"
    },
    {
        "action": "wait",
        "condition": "element",
        "selector": ".success-message",
        "timeout": 10,
        "description": "Wait for confirmation"
    },
    {
        "action": "screenshot",
        "filepath": "./confirmation.png",
        "description": "Capture confirmation"
    }
]

result = await tool.execute(steps=steps)
```

### Example 4: Data Extraction with Pagination

```python
steps = [
    {
        "action": "navigate",
        "url": "https://example.com/data",
        "description": "Navigate to data page"
    },
    {
        "action": "loop",
        "condition": "document.querySelector('.next-page:not(.disabled)') !== null",
        "max_iterations": 50,
        "actions": [
            {
                "action": "get_text",
                "selector": "table tr",
                "multiple": True,
                "extract_type": "html",
                "description": "Extract table rows"
            },
            {
                "action": "click",
                "selector": ".next-page",
                "wait_after_click": "table",
                "description": "Go to next page"
            },
            {
                "action": "wait",
                "duration": 1
            }
        ],
        "description": "Extract data from all pages"
    }
]

result = await tool.execute(steps=steps)
```

### Example 5: Authenticated Session with Cookies

```python
steps = [
    {
        "action": "navigate",
        "url": "https://example.com",
        "description": "Navigate to site"
    },
    {
        "action": "set_cookies",
        "cookies": [
            {
                "name": "auth_token",
                "value": "your_token_here",
                "domain": "example.com",
                "secure": True
            }
        ],
        "description": "Set authentication cookies"
    },
    {
        "action": "refresh",
        "description": "Reload with authentication"
    },
    {
        "action": "wait",
        "condition": "element",
        "selector": ".user-profile",
        "description": "Wait for authenticated content"
    },
    {
        "action": "get_text",
        "selector": ".user-name",
        "description": "Get username"
    }
]

result = await tool.execute(steps=steps)
```

---

## Best Practices

### 1. Always Use Descriptions
Add clear descriptions to each action for better debugging and logging:

```python
{
    "action": "click",
    "selector": "#submit",
    "description": "Submit the registration form"  # Good practice
}
```

### 2. Use Appropriate Waits
Don't rely solely on fixed delays. Use conditional waits:

```python
# Good
{
    "action": "wait",
    "condition": "element_visible",
    "selector": ".results"
}

# Avoid when possible
{
    "action": "wait",
    "duration": 5  # Fixed delays are fragile
}
```

### 3. Handle Dynamic Content
For AJAX-heavy sites, wait for specific elements or network idle:

```python
{
    "action": "await_browser_event",
    "event_type": "networkidle",
    "timeout": 10
}
```

### 4. Use Loops for Repetitive Tasks
Instead of repeating actions, use loops:

```python
{
    "action": "loop",
    "iterations": 10,
    "actions": [
        {"action": "click", "selector": ".load-more"},
        {"action": "wait", "duration": 2}
    ]
}
```

### 5. Selector Best Practices
- Prefer ID selectors: `#unique-id`
- Use data attributes: `[data-testid='submit']`
- Avoid brittle class names: `.btn-primary` may change
- Use text selectors carefully: `selector_type: "text"`

### 6. Error Handling
Set appropriate timeouts and use `break_on_error` in loops:

```python
{
    "action": "loop",
    "iterations": 5,
    "break_on_error": True,  # Stop on first error
    "actions": [...]
}
```

### 7. Screenshots for Debugging
Capture screenshots at key points:

```python
{
    "action": "screenshot",
    "filepath": "./debug/step_5.png",
    "description": "Debug screenshot after form submission"
}
```

---

## Error Handling

The tool includes automatic retry logic and error handling. Results are stored in the `results` attribute:

```python
tool = WebScrapingTool()
result = await tool.execute(steps=steps)

# Check for errors
if result.get("error"):
    print(f"Error: {result['error']}")
else:
    print(f"Success: {result}")
```

---

## Advanced Configuration

### Mobile Emulation

```python
tool = WebScrapingTool(
    browser='chrome',
    mobile=True,
    mobile_device='iPhone 14 Pro Max'
)
```

### Custom User Agent

```python
tool = WebScrapingTool(
    browser='chrome',
    custom_user_agent='Mozilla/5.0 (Custom) ...'
)
```

### Disable Resources for Speed

```python
tool = WebScrapingTool(
    browser='chrome',
    disable_images=True,
    disable_javascript=False  # Usually keep JS enabled
)
```

### Undetected Chrome (Anti-bot)

```python
tool = WebScrapingTool(
    browser='undetected',
    headless=False
)
```

---

## Integration with AI-Parrot

The WebScrapingTool integrates seamlessly with AI-Parrot's LLM capabilities for intelligent scraping workflows:

```python
from aiparrot import Agent
from aiparrot.tools import WebScrapingTool

scraper = WebScrapingTool(browser='chrome')

agent = Agent(
    name="WebScraperAgent",
    tools=[scraper],
    llm=your_llm_client
)

response = await agent.run(
    "Navigate to example.com and extract all product information"
)
```

The LLM can generate the appropriate steps dynamically based on natural language instructions.
