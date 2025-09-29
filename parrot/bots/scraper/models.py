from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field, HttpUrl

class ScrapingStepSchema(BaseModel):
    """Schema for a single scraping step"""
    action: Literal['navigate', 'click', 'fill', 'wait', 'scroll', 'authenticate']
    target: str = Field(
        ...,
        description="For navigate: full URL (e.g., 'https://example.com'). "
                    "For click/fill/wait: CSS selector (e.g., '#search-box', '.button'). "
                    "Must be a concrete selector or URL, not a description."
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
