from typing import Optional, Dict, Union, List, Any
from datetime import datetime
import json
from pydantic import BaseModel, Field, field_validator, ConfigDict
from navconfig import BASE_DIR
from asyncdb import AsyncDB
from asyncdb.models import Model, Field as ModelField
from querysource.conf import default_dsn
from ..abstract import AbstractTool



class ProductInput(BaseModel):
    """Input schema for product information requests."""
    model: str = Field(
        ..., description="The product model identifier (e.g., 'X1234', 'Y5678')."
    )
    program_slug: str = Field(
        ..., description="The program slug associated with the product (e.g., 'alpha', 'beta')."
    )


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

        # Use static_dir if configured, otherwise fall back to BASE_DIR
        base_path = self.static_dir if hasattr(self, 'static_dir') and self.static_dir else BASE_DIR

        # Try multiple paths for backward compatibility
        # 1. Direct path (for when static_dir points to programs/ or taskstore/programs/)
        query_file = base_path / program_slug / 'sql' / 'products.sql'

        # 2. Try with 'programs/' prefix (for when static_dir points to base directory)
        if not query_file.exists():
            query_file = base_path / 'programs' / program_slug / 'sql' / 'products.sql'

        # 3. Fallback to old structure: agents/product_report/{program_slug}/products.sql
        if not query_file.exists():
            query_file = base_path / 'agents' / 'product_report' / program_slug / 'products.sql'

        if not query_file.exists():
            raise FileNotFoundError(
                f"Query file not found for program_slug '{program_slug}'. Tried:\n"
                f"  - {base_path / program_slug / 'sql' / 'products.sql'}\n"
                f"  - {base_path / 'programs' / program_slug / 'sql' / 'products.sql'}\n"
                f"  - {base_path / 'agents' / 'product_report' / program_slug / 'products.sql'}"
            )

        query = query_file.read_text()
        async with await db.connection() as conn:  # noqa
            product_data, error = await conn.query(query, model)
            if error:
                raise RuntimeError(f"Database query failed: {error}")
            if not product_data:
                raise ValueError(f"No product found with model '{model}' in program '{program_slug}'.")

            return ProductInfo(**product_data[0])


class ProductListInput(BaseModel):
    """Input schema for product list requests."""
    program_slug: str = Field(
        ..., description="The program slug to get products from (e.g., 'google', 'hisense')."
    )
    models: Optional[List[str]] = Field(
        default=None, description="Optional list of specific models to get. If None, gets all models."
    )


class ProductListTool(AbstractTool):
    """Tool to get list of products for a given program/tenant."""
    name = "get_products_list"
    description = (
        "Use this tool to get a list of products for a given program/tenant. "
        "Provide the program slug as input. Optionally provide a list of specific models."
    )
    args_schema = ProductListInput

    async def _execute(self, program_slug: str, models: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """Get list of products for a program."""
        db = AsyncDB('pg', dsn=default_dsn)

        # Use static_dir if configured, otherwise fall back to BASE_DIR
        base_path = self.static_dir if hasattr(self, 'static_dir') and self.static_dir else BASE_DIR

        # Determine which SQL file to use
        file_type = 'product_single.sql' if models else 'products_list.sql'

        # Try multiple paths for backward compatibility
        # 1. Direct path (for when static_dir points to programs/ or taskstore/programs/)
        query_file = base_path / program_slug / 'sql' / file_type

        # 2. Try with 'programs/' prefix (for when static_dir points to base directory)
        if not query_file.exists():
            query_file = base_path / 'programs' / program_slug / 'sql' / file_type

        # 3. Fallback to old structure: agents/product_report/{program_slug}/<file>
        if not query_file.exists():
            query_file = base_path / 'agents' / 'product_report' / program_slug / file_type

        if not query_file.exists():
            raise FileNotFoundError(
                f"Products query file not found for program_slug '{program_slug}'. Tried:\n"
                f"  - {base_path / program_slug / 'sql' / file_type}\n"
                f"  - {base_path / 'programs' / program_slug / 'sql' / file_type}\n"
                f"  - {base_path / 'agents' / 'product_report' / program_slug / file_type}"
            )

        query = query_file.read_text()
        async with await db.connection() as conn:  # noqa
            if models:
                # Execute with models parameter
                products, error = await conn.query(query, models)
            else:
                # Execute without parameters
                products, error = await conn.query(query)

            if error:
                raise RuntimeError(f"Database query failed: {error}")
            if not products:
                return []

            return products


class ProductResponse(Model):
    """
    ProductResponse is a model that defines the structure of the response for Product agents.
    """
    model: Optional[str] = ModelField(
        default=None,
        description="Model of the product"
    )
    program_slug: Optional[str] = ModelField(
        default=None,
        description="Program/tenant identifier"
    )
    agent_id: Optional[str] = ModelField(
        default=None,
        description="Unique identifier for the agent that processed the request"
    )
    agent_name: Optional[str] = ModelField(
        default="ProductReport",
        description="Name of the agent that processed the request"
    )
    status: str = ModelField(default="success", description="Status of the response")
    data: Optional[str] = ModelField(
        default=None,
        description="Data returned by the agent, can be text, JSON, etc."
    )
    # Optional output field for structured data
    output: Optional[Any] = ModelField(
        default=None,
        description="Output of the agent's processing"
    )
    attributes: Dict[str, str] = ModelField(
        default_factory=dict,
        description="Attributes associated with the response"
    )
    # Timestamp
    created_at: datetime = ModelField(
        default_factory=datetime.now, description="Timestamp when response was created"
    )
    # Optional file paths
    transcript: Optional[str] = ModelField(
        default=None, description="Transcript of the conversation with the agent"
    )
    script_path: Optional[str] = ModelField(
        default=None, description="Path to the conversational script associated with the session"
    )
    podcast_path: Optional[str] = ModelField(
        default=None, description="Path to the podcast associated with the session"
    )
    pdf_path: Optional[str] = ModelField(
        default=None, description="Path to the PDF associated with the session"
    )
    document_path: Optional[str] = ModelField(
        default=None, description="Path to any document generated during session"
    )
    # complete list of generated files:
    files: List[str] = ModelField(
        default_factory=list, description="List of documents generated during the session")

    class Meta:
        """Meta class for ProductResponse."""
        name = "products_informations"
        schema = "product_report"
        strict = True
        frozen = False
