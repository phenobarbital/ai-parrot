"""Shape profiles: what the classical-CV proposer should look for (FEAT-574)."""

from __future__ import annotations

from typing import Literal, Tuple

from pydantic import BaseModel, Field, model_validator


class ShapeProfile(BaseModel):
    """Geometric/photometric description of one kind of shape to propose.

    All size bands are fractions of the evaluated image (width for widths, height for heights),
    so a profile is independent of the photo resolution.
    """

    name: str
    kind: str = Field(description="ShapeKind value; a plain str so this module has no cycle-contract import")
    min_width: float = Field(gt=0.0, le=1.0)
    max_width: float = Field(gt=0.0, le=1.0)
    min_height: float = Field(gt=0.0, le=1.0)
    max_height: float = Field(gt=0.0, le=1.0)
    min_aspect: float = Field(gt=0.0)
    max_aspect: float = Field(gt=0.0)
    polarity: Literal["bright", "dark", "edge"]
    min_rectangularity: float = Field(default=0.75, ge=0.0, le=1.0)
    min_contrast_std: float = Field(default=25.0, ge=0.0)
    thresholds: Tuple[int, ...] = (130, 150, 170, 190, 210, 230)
    dedup_overlap: float = Field(default=0.5, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_bands(self) -> "ShapeProfile":
        """Reject inverted bands and out-of-range gray thresholds.

        Returns:
            The validated profile.

        Raises:
            ValueError: A ``min_*`` bound is not strictly below its ``max_*`` bound, or a
                threshold is outside ``0..255``. The message names the offending field.
        """
        for band in ("width", "height", "aspect"):
            low = getattr(self, f"min_{band}")
            high = getattr(self, f"max_{band}")
            if low >= high:
                raise ValueError(f"min_{band} ({low}) must be < max_{band} ({high})")
        for threshold in self.thresholds:
            if not 0 <= threshold <= 255:
                raise ValueError(f"thresholds: {threshold} is outside 0..255")
        return self


class ShapeCandidate(BaseModel):
    """One proposed rectangle in SOURCE-image pixels."""

    profile: str
    kind: str
    x1: int
    y1: int
    x2: int
    y2: int
    score: float = Field(ge=0.0, le=1.0)


PRICE_TAG_PROFILE = ShapeProfile(
    name="price_tag",
    kind="price_tag",
    min_width=0.025,
    max_width=0.09,
    min_height=0.014,
    max_height=0.06,
    min_aspect=1.65,
    max_aspect=4.4,
    polarity="bright",
)
