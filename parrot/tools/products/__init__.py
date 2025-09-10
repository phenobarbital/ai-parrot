from typing import Optional, Dict, Union
from decimal import Decimal
import json
from pydantic import BaseModel, Field, field_validator, ConfigDict
from navconfig import BASE_DIR
from asyncdb import AsyncDB
from querysource.conf import default_dsn
from ..abstract import AbstractTool


class ProductInput(BaseModel):
    """Input schema for product information requests."""
    model: str = Field(..., description="The product model identifier (e.g., 'X1234', 'Y5678').")
    program_slug: str = Field(..., description="The program slug associated with the product (e.g., 'alpha', 'beta').")


class ProductInfo(BaseModel):
    """Schema for the product information returned by the query."""
    name: str
    model: str
    description: str
    picture_url: str
    brand: str
    # pricing: Decimal
    pricing: str
    customer_satisfaction: Optional[str] = None
    product_evaluation: Optional[str] = None
    product_compliant: Optional[str] = None
    # specifications: Dict[str, Union[dict, list]] = Field(
    #     default_factory=dict,
    #     description="Specifications of the product, can be a dict or list."
    # )
    specifications: Dict[str, Union[str, int, float, bool, list, dict]] = Field(
        default_factory=dict,
        description="Specifications of the product as a dictionary."
    )
    review_average: float
    reviews: int

    @field_validator('specifications', mode='before')
    @classmethod
    def parse_specifications(cls, v):
        if v is None or v == '':
            return {}
        if isinstance(v, dict):
            return v
        if isinstance(v, (bytes, bytearray)):
            v = v.decode('utf-8', errors='ignore')
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError as e:
                raise ValueError("Specifications field is not a valid JSON string.") from e
            if not isinstance(parsed, dict):
                raise TypeError("Specifications JSON must decode to a dictionary.")
            return parsed
        raise TypeError("specifications must be a dict or a JSON string.")

    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
    )

class ProductInfoTool(AbstractTool):
    """Tool to get detailed information about a specific product model."""
    name = "get_product_information"
    description = (
        "Use this tool to get detailed information about a specific product model. "
        "Provide the exact model identifier as input."
    )
    args_schema = ProductInput

    async def _execute(self, model: str, program_slug: str) -> ProductInfo:
        db = AsyncDB('pg', dsn=default_dsn)
        query_file = BASE_DIR / 'agents' / 'product_report' / program_slug / 'products.sql'
        if query_file.exists() is False:
            raise FileNotFoundError(
                f"Query file not found for program_slug '{program_slug}' at {query_file}"
            )
        query = query_file.read_text()
        async with await db.connection() as conn:
            product_data, error = await conn.query(query, model)
            if error:
                raise RuntimeError(f"Database query failed: {error}")
            if not product_data:
                raise ValueError(f"No product found with model '{model}' in program '{program_slug}'.")

            return ProductInfo(**product_data[0])
