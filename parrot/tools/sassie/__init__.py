from decimal import Decimal
from typing import List, Optional, Dict, Any, Union
from typing_extensions import Annotated
from datetime import date
import json
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datamodel.parsers.json import json_encoder  # noqa  pylint: disable=E0611
from ...exceptions import ToolError  # pylint: disable=E0611
from ..toolkit import tool_schema
from ..nextstop.base import BaseNextStop

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
    pricing: Decimal
    customer_satisfaction: Optional[str] = None
    product_evaluation: Optional[str] = None
    product_compliant: Optional[str] = None
    specifications: Dict[str, Union[dict, list]] = Field(
        default_factory=dict,
        description="Specifications of the product, can be a dict or list."
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

class ClientInput(BaseModel):
    """Input schema for client-related tools."""
    program: Optional[str] = Field(
        default='google',
        description="Program name, defaults to current program if not provided"
    )
    question: str = Field(
        None,
        description="Question ID to retrieve"
    )
    client: str = Field(default='1400', description="Unique identifier for the client")

    model_config = ConfigDict(extra="forbid")

class VisitData(BaseModel):
    """Individual visit data entry containing question and answer information."""
    question_id: str = Field(..., description="Unique identifier for the question")
    question: str = Field(..., description="The question made by the survey")
    answer: Optional[str] = Field(default='', description="Answer provided for the question")

class EvaluationRecord(BaseModel):
    """Complete evaluation record with visit data and metadata."""
    evaluation_id: str = Field(..., description="Unique evaluation identifier")
    client_name: str = Field(..., description="Name of the client")
    shopper_id: int = Field(..., description="Shopper identifier")
    visit_date: date = Field(..., description="Date of the visit")
    store_number: str = Field(..., description="Store number/identifier")
    store_name: str = Field(..., description="Name of the store")
    city: str = Field(..., description="City where the store is located")
    state_code: str = Field(..., description="State code (e.g., TX)")
    district: str = Field(..., description="District name")
    region: Optional[str] = Field(None, description="Region (may be null)")
    division: Optional[str] = Field(None, description="Division (may be null)")
    market: Optional[str] = Field(None, description="Market (may be null)")
    visit_data: List[VisitData] = Field(..., description="List of question-answer pairs from the visit")

    class Config:
        # Allow parsing of date strings
        json_encoders = {
            date: lambda v: v.isoformat()
        }


# Alternative simpler model if you only need the visit_data part
class VisitDataResponse(BaseModel):
    """Simplified model containing only the visit data."""
    visit_data: List[VisitData] = Field(..., description="List of question-answer pairs from the visit")


class VisitsToolkit(BaseNextStop):
    """Toolkit for managing employee-related operations in Sassie Survey Project.

    This toolkit provides tools to:
    - visits_survey: Get visit survey data for an specified Client.
    - get_visit_questions: Get visit questions and answers for a specific client.
    - get_product_information: Get basic product information.
    """
    async def _get_visits(
        self,
        program: str,
        client: str,
        question: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Internal method to fetch raw visit data for a specified client.
        """
        if program:
            self.program = program
        sql = await self._get_query("surveys")
        sql = sql.format(client=client, question=question)
        try:
            return await self._get_dataset(
                sql,
                output_format='structured',
                structured_obj=EvaluationRecord
            )
        except ToolError as te:
            raise ValueError(
                f"No Survey Visit data found for client {client}, error: {te}"
            )
        except Exception as e:
            raise ValueError(f"Error fetching Survey visit data: {e}"
    )

    @tool_schema(ClientInput)
    async def visits_survey(
        self,
        program: str,
        client: str,
        question: str,
        **kwargs
    ) -> List[EvaluationRecord]:
        """Fetch visit survey data for a specified client.
        """
        if program:
            self.program = program
        visits = await self._get_visits(
            program=program,
            client=client,
            question=question
        )
        # removing the column "visit_data" from the response
        for visit in visits:
            if hasattr(visit, 'visit_data'):
                delattr(visit, 'visit_data')
        return visits

    @tool_schema(ClientInput)
    async def get_visit_questions(
        self,
        program: str,
        client: str,
        question: str,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get visit information for a specific store, focusing on questions and answers.
        """
        if program:
            self.program = program
        visits = await self._get_visits(
            client=client,
            program=program,
            question=question
        )
        if isinstance(visits, str):  # If an error message was returned
            return visits

        question_data = {}
        for _, visit in enumerate(visits):
            if not visit.visit_data:
                continue
            for qa_item in visit.visit_data:
                idx = f"{qa_item.question_id} - {qa_item.question}"
                if idx not in question_data:
                    question_data[idx] = []
                if qa_item.question_id not in question_data:
                    question_data[qa_item.question_id] = []
                # reduce the size of answer to 100 characters
                if qa_item.answer and len(qa_item.answer) > 100:
                    qa_item.answer = qa_item.answer[:100] + "..."
                question_data[idx].append(
                    {
                        "answer": qa_item.answer or ''
                    }
                )
        return json_encoder(question_data)

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
            sql = await self._get_query("product_info")
            sql = sql.format(model=model)
            data = await self._get_dataset(
                sql,
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
