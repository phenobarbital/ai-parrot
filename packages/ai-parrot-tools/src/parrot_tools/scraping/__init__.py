from .tool import WebScrapingTool, WebScrapingToolArgs, ScrapingResult
from .toolkit import WebScrapingToolkit
from .toolkit_models import DriverConfig, PlanSummary, PlanSaveResult
from .plan import ScrapingPlan
from .registry import PlanRegistry
from .crawler import CrawlEngine
from .crawl_graph import CrawlResult, CrawlNode
from .crawl_strategy import BFSStrategy, DFSStrategy, CrawlStrategy
from .link_discoverer import LinkDiscoverer
from .url_utils import normalize_url
from .driver_factory import DriverFactory
from .drivers.abstract import AbstractDriver
from .drivers.playwright_config import PlaywrightConfig
from .drivers.playwright_driver import PlaywrightDriver
from .drivers.selenium_driver import SeleniumDriver
from .extraction_models import (
    EntityFieldSpec,
    EntitySpec,
    ExtractionPlan,
    ExtractedEntity,
    ExtractionResult,
)
from .base_registry import BasePlanRegistry
from .extraction_registry import ExtractionPlanRegistry
from .extraction_plan_generator import ExtractionPlanGenerator


__all__ = (
    # Legacy (deprecated)
    "WebScrapingTool",
    "WebScrapingToolArgs",
    "ScrapingResult",
    # New toolkit
    "WebScrapingToolkit",
    "DriverConfig",
    "PlanSummary",
    "PlanSaveResult",
    # Plan & registry
    "ScrapingPlan",
    "PlanRegistry",
    # Crawl engine
    "CrawlEngine",
    "CrawlResult",
    "CrawlNode",
    "BFSStrategy",
    "DFSStrategy",
    "CrawlStrategy",
    "LinkDiscoverer",
    "normalize_url",
    # Driver abstraction
    "DriverFactory",
    "AbstractDriver",
    "PlaywrightConfig",
    "PlaywrightDriver",
    "SeleniumDriver",
    # Extraction models
    "EntityFieldSpec",
    "EntitySpec",
    "ExtractionPlan",
    "ExtractedEntity",
    "ExtractionResult",
    # Registries
    "BasePlanRegistry",
    "ExtractionPlanRegistry",
    # Generators
    "ExtractionPlanGenerator",
)
