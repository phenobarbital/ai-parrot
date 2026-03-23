from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field, field_validator

class ScrapingStepSchema(BaseModel):
    """Schema for a single scraping step"""
    action: Literal['navigate', 'click', 'fill', 'wait', 'scroll', 'authenticate', 'await_human', 'await_keypress', 'await_browser_event']
    target: Optional[str] = Field(
        None,
        description="For navigate: full URL (e.g., 'https://example.com'). "
                    "For click/fill/wait: CSS selector (e.g., '#search-box', '.button'). "
                    "Must be a concrete selector or URL, not a description. "
                    "When action is a await, target can be None."
    )
    value: Optional[str] = Field(
        None,
        description="Value to fill (for 'fill' action only)"
    )
    wait_condition: Optional[str] = Field(
        None,
        description="Wait condition like 'visibility_of_element' or 'element_to_be_clickable'"
    )
    timeout: int = Field(
        default=10,
        description="Timeout in seconds",
        ge=1,
        le=60
    )
    description: str = Field(
        ...,
        description="Human-readable description of what this step does"
    )

    @field_validator('target')
    @classmethod
    def validate_target(cls, v: str, info) -> str:
        action = info.data.get('action')

        if action == 'navigate':
            if not (v.startswith('http://') or v.startswith('https://')):
                raise ValueError(f"Navigate target must be a full URL, got: {v}")

        elif action in ['fill', 'click', 'wait']:
            # Check if it looks like a selector (not natural language)
            if len(v) > 150 or ' the ' in v.lower() or ' and ' in v.lower():
                raise ValueError(f"Target looks like natural language, not a selector: {v}")

            # Must contain selector patterns
            if not any(char in v for char in ['.', '#', '[', ':', '>']):
                raise ValueError(f"Target doesn't look like a CSS selector: {v}")

        return v

class ScrapingSelectorSchema(BaseModel):
    """Schema for content extraction selector"""
    name: str = Field(..., description="Identifier for this selector")
    selector: str = Field(
        ...,
        description="CSS selector (e.g., '.product-title', '#price')"
    )
    selector_type: Literal['css', 'xpath'] = Field(
        default='css',
        description="Type of selector"
    )
    extract_type: Literal['text', 'html', 'attribute'] = Field(
        default='text',
        description="What to extract"
    )
    attribute: Optional[str] = Field(
        None,
        description="Attribute name if extract_type is 'attribute'"
    )
    multiple: bool = Field(
        default=False,
        description="Whether to extract multiple elements"
    )

class BrowserConfigSchema(BaseModel):
    """Schema for browser configuration"""
    browser: Literal['chrome', 'firefox', 'edge', 'safari', 'undetected'] = Field(
        default='chrome',
        description="Browser to use"
    )
    headless: bool = Field(
        default=True,
        description="Run in headless mode"
    )
    mobile: bool = Field(
        default=False,
        description="Emulate mobile device"
    )
    mobile_device: Optional[str] = Field(
        None,
        description="Specific mobile device to emulate"
    )

class ScrapingPlanSchema(BaseModel):
    """Complete scraping plan with steps, selectors, and config"""
    analysis: str = Field(
        ...,
        description="Brief analysis of the scraping challenge and approach"
    )
    browser_config: BrowserConfigSchema = Field(
        ...,
        description="Recommended browser configuration"
    )
    steps: List[ScrapingStepSchema] = Field(
        ...,
        description="Ordered list of navigation/interaction steps",
        min_length=1
    )
    selectors: List[ScrapingSelectorSchema] = Field(
        default_factory=list,
        description="Content extraction selectors"
    )
    risks: List[str] = Field(
        default_factory=list,
        description="Potential challenges and risks"
    )
    fallback_strategy: Optional[str] = Field(
        None,
        description="What to do if the plan fails"
    )
