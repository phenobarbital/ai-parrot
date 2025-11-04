"""
Browser Action System for AI-Parrot WebScrapingTool
Object-oriented action hierarchy for LLM-directed browser automation
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any, Union, Literal, Annotated
from abc import ABC
import time
from dataclasses import dataclass, field
from pydantic import BaseModel, Field, field_validator
from bs4 import BeautifulSoup


class BrowserAction(BaseModel, ABC):
    """Base class for all browser actions"""
    name: str = Field(default="", description="Optional name for this action")
    # add a generic action field so the key exists on all models
    action: str = Field(default="", description="Action opcode used for union discrimination")
    description: str = Field(default="", description="Human-readable description of this action")
    timeout: Optional[int] = Field(
        default=None, description="Maximum time to wait for action completion (seconds), None for no wait."
    )

    def get_action_type(self) -> str:
        """Return the action type identifier"""
        return self.name


class Navigate(BrowserAction):
    """Navigate to a URL"""
    name: str = 'navigate'
    action: Literal["navigate"] = "navigate"
    url: str = Field(description="Target URL to navigate to")
    description: str = Field(default="Navigate to a URL", description="navigating to a specific URL")


class Click(BrowserAction):
    """Click on a web page element"""
    name: str = "click"
    action: Literal["click"] = "click"
    selector: str = Field(description="CSS or XPATH selector to identify the target element")
    description: str = Field(default="Click on an element", description="clicking on a specific element")
    selector_type: Literal["css", "xpath", "text"] = Field(
        default="css",
        description="Type of selector: 'css' for CSS selectors, 'xpath' for XPath, 'text' for text matching"
    )
    click_type: Literal["single", "double", "right"] = Field(
        default="single",
        description="Type of click action"
    )
    wait_after_click: Optional[str] = Field(
        default=None,
        description="Optional CSS selector of element to wait for after clicking"
    )
    wait_timeout: int = Field(default=2, description="Timeout for post-click wait (seconds)")
    no_wait: bool = Field(default=False, description="Skip any waiting after click")

class Fill(BrowserAction):
    """Fill text into an input field"""
    name: str = 'fill'
    action: Literal['fill'] = 'fill'
    description: str = Field(default="Fill an input field", description="Filling a specific input field")
    selector: str = Field(description="CSS selector to identify the input field")
    value: str = Field(description="Text to enter into the field")
    clear_first: bool = Field(default=True, description="Clear existing content before filling")
    press_enter: bool = Field(default=False, description="Press Enter after filling")

class Select(BrowserAction):
    """ Select an option from a dropdown/select element."""
    name: str = 'select'
    action: Literal['select'] = 'select'
    description: str = Field(
        default="Select dropdown option",
        description="Selecting an option from a dropdown/select element"
    )
    selector: str = Field(description="CSS selector to identify the select element")
    value: Optional[str] = Field(
        default=None,
        description="Value attribute of the option to select"
    )
    text: Optional[str] = Field(
        default=None,
        description="Visible text of the option to select"
    )
    index: Optional[int] = Field(
        default=None,
        description="Index of the option to select (0-based)"
    )
    by: Literal['value', 'text', 'index'] = Field(
        default='value',
        description="Selection method: 'value' (by value attribute), 'text' (by visible text), or 'index' (by position)"
    )
    blur_after: bool = Field(
        default=True,
        description="Trigger blur/change events after selection (lose focus)"
    )
    wait_after_select: Optional[str] = Field(
        default=None,
        description="Optional CSS selector to wait for after selecting"
    )
    wait_timeout: int = Field(
        default=2,
        description="Timeout for post-select wait (seconds)"
    )

    @field_validator('value', 'text', 'index')
    @classmethod
    def validate_selection_params(cls, v, info):
        """Ensure at least one selection parameter is provided"""
        if info.data.get('by') == 'value' and not info.data.get('value'):
            raise ValueError("'value' must be provided when by='value'")
        if info.data.get('by') == 'text' and not info.data.get('text'):
            raise ValueError("'text' must be provided when by='text'")
        if info.data.get('by') == 'index' and info.data.get('index') is None:
            raise ValueError("'index' must be provided when by='index'")
        return v


class Evaluate(BrowserAction):
    """Execute JavaScript code in the browser context"""
    name: str = 'evaluate'
    action: Literal['evaluate'] = 'evaluate'
    description: str = Field(default="Evaluate JavaScript", description="Executing custom JavaScript code")
    script: Optional[str] = Field(default=None, description="JavaScript code to execute")
    script_file: Optional[str] = Field(default=None, description="Path to JavaScript file to load and execute")
    args: List[Any] = Field(default_factory=list, description="Arguments to pass to the script")
    return_value: bool = Field(
        default=True,
        description="Whether to return the script's result"
    )

    @field_validator('script', 'script_file')
    @classmethod
    def validate_script_source(cls, v, info):
        """Ensure either script or script_file is provided, but not both"""
        script = info.data.get('script')
        if script and v:
            raise ValueError("Provide either 'script' or 'script_file', not both")
        return v


class PressKey(BrowserAction):
    """Press keyboard keys"""
    name: str = 'press_key'
    action: Literal['press_key'] = 'press_key'
    description: str = Field(default="Press keyboard keys", description="Pressing specified keyboard keys")
    keys: List[str] = Field(description="List of keys to press (e.g., ['Tab', 'Enter', 'Escape'])")
    sequential: bool = Field(default=True, description="Press keys sequentially or as a combination")
    target: Optional[str] = Field(default=None, description="CSS selector to focus before pressing keys")


class Refresh(BrowserAction):
    """Reload the current web page"""
    name: str = 'refresh'
    action: Literal['refresh'] = 'refresh'
    description: str = Field(default="Refresh the page", description="Reloading the current page")
    hard: bool = Field(default=False, description="Perform hard refresh (clear cache)")


class Back(BrowserAction):
    """Navigate back to the previous page"""
    name: str = 'back'
    action: Literal['back'] = 'back'
    description: str = Field(default="Go back in history", description="Navigating back in browser history")
    steps: int = Field(default=1, description="Number of steps to go back in history")


class Scroll(BrowserAction):
    """Scroll the page or an element"""
    name: str = 'scroll'
    action: Literal['scroll'] = 'scroll'
    description: str = Field(default="Scroll the page or an element", description="Scrolling the page or a specific element")
    direction: Literal["up", "down", "top", "bottom"] = Field(description="Scroll direction")
    amount: Optional[int] = Field(default=None, description="Pixels to scroll (if not to top/bottom)")
    selector: Optional[str] = Field(default=None, description="CSS selector of element to scroll (default: page)")
    smooth: bool = Field(default=True, description="Use smooth scrolling animation")


class GetCookies(BrowserAction):
    """Extract and evaluate cookies"""
    name: str = 'get_cookies'
    action: Literal['get_cookies'] = 'get_cookies'
    description: str = Field(default="Get cookies", description="Extracting cookies from the browser")
    names: Optional[List[str]] = Field(default=None, description="Specific cookie names to retrieve (None = all)")
    domain: Optional[str] = Field(default=None, description="Filter cookies by domain")


class SetCookies(BrowserAction):
    """Set cookies on the current page or domain"""
    name: str = 'set_cookies'
    action: Literal['set_cookies'] = 'set_cookies'
    description: str = Field(default="Set cookies", description="Setting cookies in the browser")
    cookies: List[Dict[str, Any]] = Field(
        description="List of cookie objects with 'name', 'value', and optional 'domain', 'path', 'secure', etc."
    )


class Wait(BrowserAction):
    """Wait for a condition to be met"""
    name: str = 'wait'
    action: Literal['wait'] = 'wait'
    description: str = Field(default="Wait for a condition", description="Waiting for a specific condition")
    condition: Optional[str] = Field(default=None, description="Value for the condition (selector, URL substring, etc.)")
    condition_type: Literal["simple", "selector", "url_contains", "url_is", "title_contains", "custom"] = Field(
        default="selector",
        description="Type of condition to wait for"
    )
    custom_script: Optional[str] = Field(
        default=None,
        description="JavaScript that returns true when condition is met (for custom type)"
    )
    timeout: int = Field(default=None, description="Maximum wait time (seconds)")


class Authenticate(BrowserAction):
    """Handle authentication flows"""
    name: str = 'authenticate'
    action: Literal['authenticate'] = 'authenticate'
    description: str = Field(default="Authenticate user", description="Performing user authentication")
    method: Literal["form", "basic", "oauth", "custom"] = Field(default="form", description="Authentication method")
    username: Optional[str] = Field(default=None, description="Username/email")
    password: Optional[str] = Field(default=None, description="Password")
    username_selector: str = Field(default="#username", description="CSS selector for username field")
    enter_on_username: bool = Field(
        default=False,
        description="Press Enter after filling username (for multi-step logins)"
    )
    password_selector: str = Field(default="#password", description="CSS selector for password field")
    submit_selector: str = Field(
        default='input[type="submit"], button[type="submit"]',
        description="CSS selector for submit button"
    )
    custom_steps: Optional[List[BrowserAction]] = Field(
        default=None,
        description="Custom action sequence for complex authentication"
    )
    token: Optional[str] = Field(
        default=None,
        description="The bearer token value (for 'bearer' method)"
    )
    header_name: str = Field(
        default="Authorization",
        description="The name of the HTTP header to set, e.g., 'Authorization' or 'X-API-Key' (for 'bearer' method)"
    )
    header_value_format: str = Field(
        default="Bearer {}",
        description="Format for the header value, where '{}' will be replaced by the token (for 'bearer' method)"
    )


class AwaitHuman(BrowserAction):
    """Pause and wait for human intervention"""
    name: str = 'await_human'
    action: Literal['await_human'] = 'await_human'
    description: str = Field(default="Wait for human intervention", description="Waiting for user to complete a task")
    target: Optional[str] = Field(
        default=None,
        description="Target or condition value (e.g., CSS selector) to detect completion"
    )
    condition_type: Literal["selector", "url_contains", "title_contains", "manual"] = Field(
        default="selector",
        description="Condition type that indicates human completed their task"
    )
    message: str = Field(
        default="Waiting for human intervention...",
        description="Message to display while waiting"
    )
    timeout: int = Field(default=300, description="Maximum wait time (default: 5 minutes)")


class AwaitKeyPress(BrowserAction):
    """Wait for human to press a key in console"""
    name: str = 'await_keypress'
    action: Literal['await_keypress'] = 'await_keypress'
    description: str = Field(default="Wait for key press", description="Waiting for user to press a key")
    expected_key: Optional[str] = Field(
        default=None,
        description="Specific key to wait for (None = any key)"
    )
    message: str = Field(
        default="Press any key to continue...",
        description="Message to display to user"
    )
    timeout: int = Field(default=300, description="Maximum wait time (default: 5 minutes)")

class AwaitBrowserEvent(BrowserAction):
    """Wait for human interaction in the browser"""
    name: str = 'await_browser_event'
    action: Literal['await_browser_event'] = 'await_browser_event'
    target: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        description="Target or condition value to detect completion (e.g., key combo, local storage key)"
    )
    description: str = Field(
        default="Wait for browser event",
        description="Waiting for user to trigger a browser event"
    )
    wait_condition: Dict[str, Any] = Field(
        default_factory=dict,
        description="Condition to detect human completion (e.g., key combo, button or local storage key)"
    )
    timeout: int = Field(default=300, description="Maximum wait time (default: 5 minutes)")

    def get_action_type(self) -> str:
        return "await_browser_event"

class GetText(BrowserAction):
    """Extract pure text content from elements matching selector"""
    name: str = 'get_text'
    action: Literal['get_text'] = 'get_text'
    description: str = Field(default="Extract text content", description="Extracting text from elements")
    selector: str = Field(description="CSS selector to identify elements to extract text from")
    multiple: bool = Field(default=False, description="Extract from all matching elements or just first")
    extract_name: str = Field(default="extracted_text", description="Name for the extracted data in results")

class Screenshot(BrowserAction):
    """Take a screenshot of the page or a specific element"""
    name: str = 'screenshot'
    action: Literal['screenshot'] = 'screenshot'
    description: str = Field(default="Take screenshot", description="Taking a screenshot")
    selector: Optional[str] = Field(default=None, description="CSS selector of element to screenshot (None = full page)")
    full_page: bool = Field(default=True, description="Capture full scrollable page")
    output_path: Optional[str] = Field(default=None, description="Directory path to save screenshot (e.g., 'screenshots/') ")
    output_name: Optional[str] = Field(default=None, description="Filename for the screenshot (e.g., 'page.png'). If None, a timestamped name will be used.")
    return_base64: bool = Field(default=False, description="Return screenshot as base64 string in results")

    def get_filename(self) -> str:
        """Generate a filename for the screenshot"""
        if self.output_name:
            if not self.output_name.lower().endswith('.png'):  # pylint: disable=E1101 # noqa
                return f"{self.output_name}.png"
            return self.output_name
        return f"screenshot_{int(time.time())}.png"

class GetHTML(BrowserAction):
    """Extract complete HTML content from elements matching selector"""
    name: str = 'get_html'
    action: Literal['get_html'] = 'get_html'
    description: str = Field(default="Extract HTML content", description="Extracting HTML from elements")
    selector: str = Field(description="CSS or XPath selector to identify elements to extract HTML from")
    selector_type: Literal["css", "xpath"] = Field(
        default="css",
        description="Type of selector: 'css' for CSS selectors, 'xpath' for XPath"
    )
    multiple: bool = Field(default=False, description="Extract from all matching elements or just first")
    extract_name: str = Field(default="extracted_html", description="Name for the extracted data in results")


class WaitForDownload(BrowserAction):
    """Wait for a file download to complete"""
    name: str = 'wait_for_download'
    action: Literal['wait_for_download'] = 'wait_for_download'
    description: str = Field(default="Wait for download", description="Waiting for file download to complete")
    filename_pattern: Optional[str] = Field(
        default=None,
        description="Filename pattern to match (e.g., '*.pdf', 'report*.xlsx'). None = any file"
    )
    download_path: Optional[str] = Field(
        default=None,
        description="Directory to monitor for downloads (None = browser default download directory)"
    )
    timeout: int = Field(default=60, description="Maximum time to wait for download (seconds)")
    move_to: Optional[str] = Field(
        default=None,
        description="Optional path to move the downloaded file after completion"
    )
    delete_after: bool = Field(default=False, description="Delete the file after successful download detection")


class UploadFile(BrowserAction):
    """Upload a file to a file input element"""
    name: str = 'upload_file'
    action: Literal['upload_file'] = 'upload_file'
    description: str = Field(default="Upload file", description="Uploading a file to an input element")
    selector: str = Field(description="CSS selector for the file input element")
    file_path: str = Field(description="Absolute or relative path to the file to upload")
    wait_after_upload: Optional[str] = Field(
        default=None,
        description="Optional CSS selector to wait for after upload (e.g., confirmation message)"
    )
    wait_timeout: int = Field(default=10, description="Timeout for post-upload wait (seconds)")
    multiple_files: bool = Field(default=False, description="Whether uploading multiple files")
    file_paths: Optional[List[str]] = Field(
        default=None,
        description="List of file paths for multiple file upload"
    )

class Conditional(BrowserAction):
    """Execute actions conditionally based on a JavaScript expression"""
    name: str = 'conditional'
    action: Literal['conditional'] = 'conditional'
    description: str = Field(default="Conditional action execution", description="Executing actions based on a condition")
    target: Optional[str] = Field(
        default=None,
        description="Target or condition value (e.g., XPATH or CSS selector) to detect completion"
    )
    target_type: Literal["css", "xpath"] = Field(
        default="css",
        description="Type of target selector"
    )
    condition_type: Literal["text_contains", "exists", "not_exists", "text_equals", "attribute_equals"] = Field(
        default="text_contains",
        description="Condition type that determines how to evaluate the target"
    )
    expected_value: str = Field(description="Value that evaluates to true or false")
    timeout: int = Field(default=5, description="Maximum time to wait for condition evaluation (seconds)")
    actions_if_true: Optional[List["ActionList"]] = Field(
        default=None,
        description="List of actions to execute if condition is true"
    )
    actions_if_false: Optional[List["ActionList"]] = Field(
        default=None,
        description="List of actions to execute if condition is false"
    )

class Loop(BrowserAction):
    """Repeat a sequence of actions multiple times"""
    name: str = "loop"
    action: Literal["loop"] = "loop"
    description: str = Field(default="Loop over actions", description="Repeating a set of actions")
    actions: List["ActionList"] = Field(description="List of actions to execute in each iteration")
    iterations: Optional[int] = Field(default=None, description="Number of times to repeat (None = until condition)")
    condition: Optional[str] = Field(
        default=None,
        description="JavaScript condition to evaluate; loop continues while true"
    )
    values: Optional[List[Any]] = Field(
        default=None,
        description="List of values to iterate over. When provided, iterations is automatically set to len(values)"
    )
    value_name: Optional[str] = Field(
        default="value",
        description="Name of the variable to hold the current value in each iteration"
    )
    break_on_error: bool = Field(default=True, description="Stop loop if any action fails")
    max_iterations: int = Field(default=100, description="Safety limit for condition-based loops")
    start_index: int = Field(
        default=0,
        description="Starting index for iteration counter (default: 0 for 0-based indexing)"
    )
    do_replace: bool = Field(
        default=True,
        description="Whether to replace {{index}} and {{index_1}} in action parameters"
    )

ActionList = Annotated[
    Union[
        Navigate, Click, Fill, Select, Evaluate, PressKey, Refresh, Back, Scroll,
        GetCookies, SetCookies, Wait, Authenticate,
        AwaitHuman, AwaitKeyPress, AwaitBrowserEvent,
        GetText, GetHTML, WaitForDownload, UploadFile, Screenshot, Loop, Conditional
    ],
    Field(discriminator='action')
]


# Update Forward References (required for Loop containing BrowserAction)
Authenticate.model_rebuild()
Loop.model_rebuild()
Conditional.model_rebuild()

# Map action types to classes
ACTION_MAP = {
    "navigate": Navigate,
    "click": Click,
    "fill": Fill,
    "select": Select,
    "evaluate": Evaluate,
    "press_key": PressKey,
    "refresh": Refresh,
    "back": Back,
    "scroll": Scroll,
    "get_cookies": GetCookies,
    "set_cookies": SetCookies,
    "wait": Wait,
    "authenticate": Authenticate,
    "await_human": AwaitHuman,
    "await_keypress": AwaitKeyPress,
    "await_browser_event": AwaitBrowserEvent,
    "loop": Loop,
    "get_text": GetText,
    "get_html": GetHTML,
    "wait_for_download": WaitForDownload,
    "upload_file": UploadFile,
    "screenshot": Screenshot,
    "conditional": Conditional
} # :contentReference[oaicite:4]{index=4}

@dataclass
class ScrapingStep:
    """
    ScrapingStep that wraps a BrowserAction.

    Used to define a step in a scraping sequence.

    Example:
        {
            'action': 'navigate',
            'target': 'https://www.consumeraffairs.com/homeowners/service-protection-advantage.html',
            'description': 'Consumer Affairs home'
        },
    """
    action: BrowserAction
    description: str = field(default="")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        name = self.action.name
        data = self.action.model_dump()
        # Remove action_type from data
        data.pop("action_type", None)
        # remove attributes "name" and "description" from data since they are top-level keys
        data.pop("name", None)
        data.pop("description", None)
        return {
            'action': name,
            **data
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScrapingStep':
        """Create ScrapingStep from dictionary"""
        action_type = data.get('action')
        action_data = {k: v for k, v in data.items() if k != 'action'}

        action_class = ACTION_MAP.get(action_type)
        if not action_class:
            raise ValueError(
                f"Unknown action type: {action_type}"
            )

        action = action_class(**action_data)
        obj = cls(action=action)
        obj.description = data.get('description', action.description)
        if action_type == 'loop' and 'actions' in data:
            # Recursively convert nested actions
            obj.action.actions = [cls.from_dict(a).action for a in data['actions'] if isinstance(a, dict)]
        return obj


# Convenience function for LLM integration
def create_action(action_type: str, **kwargs) -> BrowserAction:
    """
    Factory function to create actions by type name
    Useful for LLM-generated action sequences
    """
    action_class = ACTION_MAP.get(action_type)
    if not action_class:
        raise ValueError(
            f"Unknown action type: {action_type}"
        )

    return action_class(**kwargs)


@dataclass
class ScrapingSelector:
    """Defines what content to extract from a page"""
    name: str  # Friendly name for the content
    selector: str  # CSS selector, XPath, or 'body' for full content
    selector_type: Literal['css', 'xpath', 'tag'] = 'css'
    extract_type: Literal['text', 'html', 'attribute'] = 'text'
    attribute: Optional[str] = None  # For attribute extraction
    multiple: bool = False  # Whether to extract all matching elements

@dataclass
class ScrapingResult:
    """Stores results from a single page scrape"""
    url: str
    content: str  # Raw HTML content
    bs_soup: BeautifulSoup  # Parsed BeautifulSoup object
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    success: bool = True
    error_message: Optional[str] = None
