"""
Browser Action System for AI-Parrot WebScrapingTool
Object-oriented action hierarchy for LLM-directed browser automation
"""
from typing import Optional, List, Dict, Any, Union, Literal
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pydantic import BaseModel, Field, field_validator


class BrowserAction(BaseModel, ABC):
    """Base class for all browser actions"""
    name: str = Field(default="", description="Optional name for this action")
    description: str = Field(default="", description="Human-readable description of this action")
    timeout: Optional[int] = Field(
        default=None, description="Maximum time to wait for action completion (seconds), None for no wait."
    )

    def get_action_type(self) -> str:
        """Return the action type identifier"""
        return self.name


class Navigate(BrowserAction):
    """Navigate to a URL"""
    name: str = "navigate"
    url: str = Field(description="Target URL to navigate to")
    description: str = Field(default="Navigate to a URL", description="navigating to a specific URL")


class Click(BrowserAction):
    """Click on a web page element"""
    name: str = "click"
    selector: str = Field(description="CSS selector to identify the target element")
    description: str = Field(default="Click on an element", description="clicking on a specific element")
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
    name: str = "fill"
    description: str = Field(default="Fill an input field", description="Filling a specific input field")
    selector: str = Field(description="CSS selector to identify the input field")
    value: str = Field(description="Text to enter into the field")
    clear_first: bool = Field(default=True, description="Clear existing content before filling")
    press_enter: bool = Field(default=False, description="Press Enter after filling")


class Evaluate(BrowserAction):
    """Execute JavaScript code in the browser context"""
    name: str = "evaluate"
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
    def validate_script_source(cls, v, values):
        """Ensure either script or script_file is provided, but not both"""
        if 'script' in values and values['script'] and v:
            raise ValueError("Provide either 'script' or 'script_file', not both")
        return v


class PressKey(BrowserAction):
    """Press keyboard keys"""
    name: str = "press_key"
    description: str = Field(default="Press keyboard keys", description="Pressing specified keyboard keys")
    keys: List[str] = Field(description="List of keys to press (e.g., ['Tab', 'Enter', 'Escape'])")
    sequential: bool = Field(default=True, description="Press keys sequentially or as a combination")
    target: Optional[str] = Field(default=None, description="CSS selector to focus before pressing keys")


class Refresh(BrowserAction):
    """Reload the current web page"""
    name: str = "refresh"
    description: str = Field(default="Refresh the page", description="Reloading the current page")
    hard: bool = Field(default=False, description="Perform hard refresh (clear cache)")


class Back(BrowserAction):
    """Navigate back to the previous page"""
    name: str = "back"
    description: str = Field(default="Go back in history", description="Navigating back in browser history")
    steps: int = Field(default=1, description="Number of steps to go back in history")


class Scroll(BrowserAction):
    """Scroll the page or an element"""
    name: str = "scroll"
    description: str = Field(default="Scroll the page or an element", description="Scrolling the page or a specific element")
    direction: Literal["up", "down", "top", "bottom"] = Field(description="Scroll direction")
    amount: Optional[int] = Field(default=None, description="Pixels to scroll (if not to top/bottom)")
    selector: Optional[str] = Field(default=None, description="CSS selector of element to scroll (default: page)")
    smooth: bool = Field(default=True, description="Use smooth scrolling animation")


class GetCookies(BrowserAction):
    """Extract and evaluate cookies"""
    name: str = "get_cookies"
    description: str = Field(default="Get cookies", description="Extracting cookies from the browser")
    names: Optional[List[str]] = Field(default=None, description="Specific cookie names to retrieve (None = all)")
    domain: Optional[str] = Field(default=None, description="Filter cookies by domain")


class SetCookies(BrowserAction):
    """Set cookies on the current page or domain"""
    name: str = "set_cookies"
    description: str = Field(default="Set cookies", description="Setting cookies in the browser")
    cookies: List[Dict[str, Any]] = Field(
        description="List of cookie objects with 'name', 'value', and optional 'domain', 'path', 'secure', etc."
    )


class Wait(BrowserAction):
    """Wait for a condition to be met"""
    name: str = "wait"
    description: str = Field(default="Wait for a condition", description="Waiting for a specific condition")
    condition_type: Literal["selector", "url_contains", "title_contains", "custom"] = Field(
        description="Type of condition to wait for"
    )
    condition_value: str = Field(description="Value for the condition (selector, URL substring, etc.)")
    custom_script: Optional[str] = Field(
        default=None,
        description="JavaScript that returns true when condition is met (for custom type)"
    )


class Authenticate(BrowserAction):
    """Handle authentication flows"""
    name: str = "authenticate"
    description: str = Field(default="Authenticate user", description="Performing user authentication")
    method: Literal["form", "basic", "oauth", "custom"] = Field(default="form", description="Authentication method")
    username: Optional[str] = Field(default=None, description="Username/email")
    password: Optional[str] = Field(default=None, description="Password")
    username_selector: str = Field(default="#username", description="CSS selector for username field")
    password_selector: str = Field(default="#password", description="CSS selector for password field")
    submit_selector: str = Field(
        default='input[type="submit"], button[type="submit"]',
        description="CSS selector for submit button"
    )
    custom_steps: Optional[List['BrowserAction']] = Field(
        default=None,
        description="Custom action sequence for complex authentication"
    )


class AwaitHuman(BrowserAction):
    """Pause and wait for human intervention"""
    name: str = "await_human"
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
    name: str = "await_keypress"
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
    name: str = "await_browser_event"
    description: str = Field(default="Wait for browser event", description="Waiting for user to trigger a browser event")
    wait_condition: Dict[str, Any] = Field(
        default_factory=dict,
        description="Condition to detect human completion (e.g., key combo, button or local storage key)"
    )
    timeout: int = Field(default=300, description="Maximum wait time (default: 5 minutes)")

    def get_action_type(self) -> str:
        return "await_browser_event"


class Loop(BrowserAction):
    """Repeat a sequence of actions multiple times"""
    name: str = "loop"
    description: str = Field(default="Loop over actions", description="Repeating a set of actions")
    actions: List[BrowserAction] = Field(description="List of actions to execute in each iteration")
    iterations: Optional[int] = Field(default=None, description="Number of times to repeat (None = until condition)")
    condition: Optional[str] = Field(
        default=None,
        description="JavaScript condition to evaluate; loop continues while true"
    )
    break_on_error: bool = Field(default=True, description="Stop loop if any action fails")
    max_iterations: int = Field(default=100, description="Safety limit for condition-based loops")

    def get_action_type(self) -> str:
        return "loop"


# Update Forward References (required for Loop containing BrowserAction)
Authenticate.model_rebuild()
Loop.model_rebuild()


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

        # Map action types to classes
        action_map = {
            "navigate": Navigate,
            "click": Click,
            "fill": Fill,
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
        }

        action_class = action_map.get(action_type)
        if not action_class:
            raise ValueError(
                f"Unknown action type: {action_type}"
            )

        action = action_class(**action_data)
        return cls(action=action)


# Convenience function for LLM integration
def create_action(action_type: str, **kwargs) -> BrowserAction:
    """
    Factory function to create actions by type name
    Useful for LLM-generated action sequences
    """
    action_map = {
        "navigate": Navigate,
        "click": Click,
        "fill": Fill,
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
    }

    action_class = action_map.get(action_type)
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
