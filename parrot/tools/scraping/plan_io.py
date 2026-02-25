"""
Plan File I/O Helpers.

Async functions to save and load ScrapingPlan instances to/from disk,
following the {plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json layout.
"""
import logging
from pathlib import Path

import aiofiles

from .plan import ScrapingPlan

logger = logging.getLogger(__name__)


async def save_plan_to_disk(plan: ScrapingPlan, plans_dir: Path) -> Path:
    """Save a ScrapingPlan to disk following the naming convention.

    File layout: {plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json
    Domain subdirectories are created automatically.

    Args:
        plan: The ScrapingPlan to save.
        plans_dir: Root directory for plan storage.

    Returns:
        Path to the saved file.
    """
    domain_dir = plans_dir / plan.domain
    domain_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{plan.name}_v{plan.version}_{plan.fingerprint}.json"
    file_path = domain_dir / filename

    async with aiofiles.open(file_path, "w") as f:
        await f.write(plan.model_dump_json(indent=2))

    logger.info("Saved plan to %s", file_path)
    return file_path


async def load_plan_from_disk(path: Path) -> ScrapingPlan:
    """Load a ScrapingPlan from a JSON file on disk.

    Args:
        path: Path to the plan JSON file.

    Returns:
        Deserialized ScrapingPlan instance.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    async with aiofiles.open(path, "r") as f:
        content = await f.read()
    return ScrapingPlan.model_validate_json(content)
