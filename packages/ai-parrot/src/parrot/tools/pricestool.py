from typing import List
from pydantic import BaseModel, Field
from datetime import date
from parrot.tools.querytoolkit import QueryToolkit
from parrot.tools.decorators import tool_schema


class PriceInput(BaseModel):
    tenant: str = Field(..., description="Program or tenant identifier (e.g. hisense, epson, etc).")
    model: str = Field(..., description="Model number of the product to query the price for.")
    week: int = Field(..., description="Week number for which to retrieve the price.")
    output_format: str = Field("structured", description="Output format: 'string' or 'structured'.")


class ModelPriceInput(BaseModel):
    tenant: str = Field(..., description="Program or tenant identifier (e.g. hisense, epson, etc).")
    model: str = Field(..., description="Model number of the product to query the price for.")
    output_format: str = Field(default="pandas", description="Output format: 'string' or 'structured'.")
    limit: int = Field(10, description="Number of records to retrieve.")


class WeeklyPriceInput(BaseModel):
    tenant: str = Field(..., description="Program or tenant identifier (e.g. hisense, epson, etc).")
    week: int = Field(..., description="Week number for which to retrieve the price.")
    output_format: str = Field(default="pandas", description="Output format: 'string' or 'structured'.")
    limit: int = Field(10, description="Number of records to retrieve.")

class TotalPriceInput(BaseModel):
    tenant: str = Field(..., description="Program or tenant identifier (e.g. hisense, epson, etc).")
    start_date: str = Field(..., description="Start date for the price query (YYYY-MM-DD).")
    end_date: str = Field(..., description="End date for the price query (YYYY-MM-DD).")
    output_format: str = Field(default="pandas", description="Output format: 'string' or 'structured'.")
    limit: int = Field(50, description="Number of records to retrieve.")


class PriceOutput(BaseModel):
    product_id: str = Field(..., description="Unique identifier for the product.")
    price: float = Field(..., description="Price of the product.")
    week: int = Field(..., description="Week number for which the price is applicable.")
    start_date: date = Field(..., description="Start date of the pricing period.")
    end_date: date = Field(..., description="End date of the pricing period.")



class PricesTool(QueryToolkit):
    """Tool for querying product prices from a database or API."""

    name = "prices_tool"
    description = "A tool to query product prices."


    @tool_schema(PriceInput, description="The price information as a string.")
    async def get_model_price(
        self,
        tenant: str,
        model: str,
        week: int,
        output_format: str = "structured",
    ) -> PriceOutput:
        """Fetches the price of a product for a given tenant, model, and week.

        Args:
            tenant (str): The program or tenant identifier.
            model (str): The model number of the product.
            week (int): The week number for     which to retrieve the price.
        """
        sql = await self._get_query("get_pricing")
        sql = sql.format(
            tenant=tenant,
            model=model,
            week=week
        )
        try:
            return await self._get_dataset(
                sql,
                output_format=output_format,
                structured_obj=PriceOutput if output_format == "structured" else None
            )
        except ValueError as ve:
            return f"No Pricing data found for the specified tenant and product, error: {ve}"
        except Exception as e:
            return f"Error fetching pricing data: {e}"

    @tool_schema(WeeklyPriceInput, description="The price information as a string.")
    async def get_weekly_price(
        self,
        tenant: str,
        week: int,
        limit: int = 10,
        output_format: str = "structured",
    ) -> List[PriceOutput]:
        """Fetches all product prices for a given tenant and week.

        Args:
            tenant (str): The program or tenant identifier.
            week (int): The week number for which to retrieve the price.
        """
        sql = await self._get_query("get_weekly_pricing")
        sql = sql.format(
            tenant=tenant,
            week=week,
            limit=limit
        )
        try:
            return await self._get_dataset(
                sql,
                output_format=output_format,
                structured_obj=PriceOutput if output_format == "structured" else None
            )
        except ValueError as ve:
            return f"No Pricing data found for the specified tenant and product, error: {ve}"
        except Exception as e:
            return f"Error fetching pricing data: {e}"
        
    @tool_schema(TotalPriceInput, description="The price information as a string.")
    async def get_price(
        self,
        tenant: str,
        start_date: str,
        end_date: str,
        limit: int = 10,
        output_format: str = "structured",
    ) -> List[PriceOutput]:
        """Fetches all product prices for a given tenant and date range.

        Args:
            tenant (str): The program or tenant identifier.
            week (int): The week number for which to retrieve the price.
        """
        sql = await self._get_query("get_total_pricing")
        sql = sql.format(
            tenant=tenant,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        try:
            return await self._get_dataset(
                sql,
                output_format=output_format,
                structured_obj=PriceOutput if output_format == "structured" else None
            )
        except ValueError as ve:
            return f"No Pricing data found for the specified tenant and product, error: {ve}"
        except Exception as e:
            return f"Error fetching pricing data: {e}"