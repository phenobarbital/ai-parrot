from typing import Optional, List, Dict, Union
from pydantic import BaseModel, Field, ConfigDict
from ..decorators import tool_schema
from ..querytoolkit import QueryToolkit
from ...exceptions import ToolError  # pylint: disable=E0611 # noqa


class ProductInput(BaseModel):
    """Input schema for querying Epson product information."""
    model: Optional[str] = Field(
        default=None,
        description="The unique identifier for the Epson product."
    )
    product_name: Optional[str] = Field(
        default=None,
        description="The name of the Epson product."
    )
    output_format: Optional[str] = Field(
        default='structured',
        description="Output format for the employee data"
    )

    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
    )


class ProductInfo(BaseModel):
    """Schema for the product information returned by the query."""
    name: str
    model: str
    description: str
    picture_url: str
    brand: str
    pricing: str
    customer_satisfaction: Optional[str] = None
    product_evaluation: Optional[str] = None
    product_compliant: Optional[str] = None
    specifications: Dict[str, Union[dict, list]] = Field(
        default_factory=dict,
        description="Specifications of the product, can be a dict or list."
    )
    review_average: float
    reviews: int

    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
    )


class EpsonProductToolkit(QueryToolkit):
    """Toolkit for managing Epson-related operations.

    This toolkit provides tools to:
    - get_product_information: Get basic product information.
    """

    @tool_schema(ProductInput)
    async def get_product_information(
        self,
        model: str,
        product_name: Optional[str] = None,
        output_format: str = 'structured',
        structured_obj: Optional[ProductInfo] = ProductInfo
    ) -> ProductInfo:
        """
        Retrieve product information for a given Epson product Model.
        """
        try:
            data = await self._get_queryslug(
                slug='epson360_products_unified',
                conditions={'model': model},
                output_format=output_format,
                structured_obj=structured_obj
            )
            if not data:
                raise ToolError(
                    f"No Product data found for model {model}."
                )
            return data
        except ToolError as te:
            raise ValueError(
                f"No Product data found for model {model}, error: {te}"
            )
        except ValueError as ve:
            raise ValueError(
                f"Invalid data format, error: {ve}"
            )
        except Exception as e:
            raise ValueError(
                f"Error fetching Product data: {e}"
            )
