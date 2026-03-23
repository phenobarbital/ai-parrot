"""AI-Parrot Pipelines package."""
from .version import __version__, __title__, __description__

PIPELINE_REGISTRY: dict[str, str] = {
    "AbstractPipeline": "parrot_pipelines.abstract.AbstractPipeline",
    "AbstractDetector": "parrot_pipelines.detector.AbstractDetector",
    "PlanogramConfig": "parrot_pipelines.models.PlanogramConfig",
    "EndcapGeometry": "parrot_pipelines.models.EndcapGeometry",
    "PlanogramCompliance": "parrot_pipelines.planogram.plan.PlanogramCompliance",
    "PlanogramCompliancePipeline": "parrot_pipelines.planogram.legacy.PlanogramCompliancePipeline",
    "RetailDetector": "parrot_pipelines.planogram.legacy.RetailDetector",
    "AbstractPlanogramType": "parrot_pipelines.planogram.types.abstract.AbstractPlanogramType",
    "ProductOnShelves": "parrot_pipelines.planogram.types.product_on_shelves.ProductOnShelves",
    "GraphicPanelDisplay": "parrot_pipelines.planogram.types.graphic_panel_display.GraphicPanelDisplay",
}

__all__ = ["__version__", "PIPELINE_REGISTRY"]
