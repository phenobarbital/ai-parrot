from typing import Optional, Dict, Union, List, Any
from decimal import Decimal
import json
from pydantic import BaseModel, Field, field_validator, ConfigDict
from navconfig import BASE_DIR
from asyncdb import AsyncDB
from querysource.conf import default_dsn
from ..abstract import AbstractTool
from datetime import datetime


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


class ProductListInput(BaseModel):
    """Input schema for product list requests."""
    program_slug: str = Field(..., description="The program slug to get products from (e.g., 'google', 'hisense').")


class ProductListTool(AbstractTool):
    """Tool to get list of all products for a given program/tenant."""
    name = "get_products_list"
    description = (
        "Use this tool to get a list of all products for a given program/tenant. "
        "Provide the program slug as input."
    )
    args_schema = ProductListInput

    async def _execute(self, program_slug: str) -> List[Dict[str, str]]:
        """Get list of all products for a program."""
        db = AsyncDB('pg', dsn=default_dsn)
        query_file = BASE_DIR / 'agents' / 'product_report' / program_slug / 'products_list.sql'
        if not query_file.exists():
            raise FileNotFoundError(
                f"Products list query file not found for program_slug '{program_slug}' at {query_file}"
            )
        
        query = query_file.read_text()
        async with await db.connection() as conn:
            products, error = await conn.query(query)
            if error:
                raise RuntimeError(f"Database query failed: {error}")
            if not products:
                return []
            
            return products


class ProductResponse(BaseModel):
    """
    ProductResponse is a model that defines the structure of the response for Product agents.
    """
    model: Optional[str] = Field(
        default=None,
        description="Model of the product"
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="Unique identifier for the agent that processed the request"
    )
    agent_name: Optional[str] = Field(
        default="ProductReport",
        description="Name of the agent that processed the request"
    )
    status: str = Field(default="success", description="Status of the response")
    data: Optional[str] = Field(
        default=None,
        description="Data returned by the agent, can be text, JSON, etc."
    )
    # Optional output field for structured data
    output: Optional[Any] = Field(
        default=None,
        description="Output of the agent's processing"
    )
    attributes: Dict[str, str] = Field(
        default_factory=dict,
        description="Attributes associated with the response"
    )
    # Timestamp
    created_at: datetime = Field(
        default_factory=datetime.now, description="Timestamp when response was created"
    )
    # Optional file paths
    transcript: Optional[str] = Field(
        default=None, description="Transcript of the conversation with the agent"
    )
    script_path: Optional[str] = Field(
        default=None, description="Path to the conversational script associated with the session"
    )
    podcast_path: Optional[str] = Field(
        default=None, description="Path to the podcast associated with the session"
    )
    pdf_path: Optional[str] = Field(
        default=None, description="Path to the PDF associated with the session"
    )
    document_path: Optional[str] = Field(
        default=None, description="Path to any document generated during session"
    )
    # complete list of generated files:
    files: List[str] = Field(
        default_factory=list, description="List of documents generated during the session")

    class Meta:
        """Meta class for ProductResponse."""
        name = "products_informations"  # Cambiado de "products_informations" a "products_information"
        schema = "product_report"  # Este se cambiará dinámicamente
        strict = True
        frozen = False
