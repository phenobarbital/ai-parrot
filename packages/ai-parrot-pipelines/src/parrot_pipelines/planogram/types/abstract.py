"""Abstract base class for planogram type composables."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Dict, Optional, Sequence, Tuple, TYPE_CHECKING

from PIL import Image

from ..contracts import (
    ComparisonResult,
    CycleContext,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
)
from ..layout import LayoutProfile

if TYPE_CHECKING:
    from ..plan import PlanogramCompliance
    from ..models import PlanogramConfig


class AbstractPlanogramType(ABC):
    """Contract for planogram type composables.

    Each composable receives a reference to the parent PlanogramCompliance
    pipeline for access to shared utilities (LLM, image helpers, config).

    Concrete implementations supply the strict cycle contract: a default
    layout profile plus the ``perceive`` / ``identify`` / ``compare`` hooks.

    Args:
        pipeline: Parent PlanogramCompliance instance providing shared
            utilities (LLM clients, image processing, config).
        config: The PlanogramConfig for this compliance run.
    """

    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE  # plan.py reads it until TASK-3871
    requires_slots_definition: ClassVar[bool] = True  # every cycle type needs a definition (plan.py until TASK-3871)
    min_usable_shapes: ClassVar[int] = 0  # plan.py until TASK-3871 (the layout profile is authoritative after)
    uses_enhanced_image: ClassVar[bool] = False  # all types receive the untouched image (spec §2)

    _CYCLE_HOOKS: ClassVar[Tuple[str, ...]] = ("default_layout_profile", "perceive", "identify", "compare")

    def __init__(
        self,
        pipeline: "PlanogramCompliance",
        config: "PlanogramConfig",
    ) -> None:
        self.pipeline = pipeline
        self.config = config
        self.logger = pipeline.logger
        self.validate_contract()

    def _implements(self, name: str) -> bool:
        """Return True when a subclass (not this base) defines ``name`` — correct for classmethods too."""
        for klass in type(self).__mro__:
            if name in klass.__dict__:
                return klass is not AbstractPlanogramType
        return False

    def validate_contract(self) -> None:
        """Reject incomplete types and configurations without a slots definition, before any inference.

        Raises:
            TypeError: A cycle hook or ``default_layout_profile`` is not implemented.
            ValueError: ``slots_definition`` is missing (names the config and the migration runbook).
        """
        missing = [name for name in self._CYCLE_HOOKS if not self._implements(name)]
        if missing:
            raise TypeError(
                f"Can't instantiate {type(self).__name__} with an incomplete planogram contract: "
                f"implement the abstract cycle members {missing}"
            )
        config_name = getattr(self.config, "config_name", None)
        if getattr(self.config, "slots_definition", None) is None:
            raise ValueError(
                f"{type(self).__name__} requires a slots_definition but config {config_name!r} has none; "
                "see docs/pipelines/planogram-cycle-migration.md"
            )

    @classmethod
    @abstractmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Return a fresh default LayoutProfile for this type (configuration overrides are merged by the pipeline)."""

    @abstractmethod
    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Stage 1: observed geometry for one untouched image (fallback is orchestrator-owned)."""

    @abstractmethod
    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Stage 2: OCR/vision identification and neutral rule evidence for one image."""

    @abstractmethod
    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Stage 3: deterministic comparison of every processed image against the definition; no I/O."""

    def fallback_detection_prompt(self) -> Optional[str]:
        """Prompt for the LLM detector fallback; ``None`` selects the generic prompt."""
        return None

    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]:
        """Return color scheme for rendering compliance overlays.

        Override in concrete types to customize colors per planogram type.

        Returns:
            Dict mapping color role to RGB tuple.
        """
        return {
            "roi": (0, 255, 0),
            "detection": (255, 165, 0),
            "product": (0, 255, 255),
            "compliant": (0, 200, 0),
            "non_compliant": (255, 0, 0),
        }
