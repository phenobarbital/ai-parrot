from typing import List, Optional, Dict, Any
from datetime import date
import json
from pydantic import BaseModel, ConfigDict, Field
from datamodel.parsers.json import json_decoder, json_encoder, JSONContent  # noqa  pylint: disable=E0611
from ...exceptions import ToolError  # pylint: disable=E0611
from ..toolkit import tool_schema
from ..nextstop.base import BaseNextStop


class ClientInput(BaseModel):
    """Input schema for client-related tools."""
    client_id: str = Field(..., description="Unique identifier for the client")
    program: Optional[str] = Field(
        None,
        description="Program name, defaults to current program if not provided"
    )

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
    """
    async def _get_visits(
        self,
        client_id: str,
        program: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Internal method to fetch raw visit data for a specified client.
        """
        if program:
            self.program = program
        sql = await self._get_query("surveys")
        sql = sql.format(client=client_id)
        try:
            return await self._get_dataset(
                sql,
                output_format='structured',
                structured_obj=EvaluationRecord
            )
        except ToolError as te:
            raise ValueError(
                f"No Survey Visit data found for client {client_id}, error: {te}"
            )
        except Exception as e:
            raise ValueError(f"Error fetching Survey visit data: {e}"
    )

    @tool_schema(ClientInput)
    async def visits_survey(
        self,
        client_id: str,
        program: str,
        **kwargs
    ) -> List[EvaluationRecord]:
        """Fetch visit survey data for a specified client.
        """
        if program:
            self.program = program
        visits = await self._get_visits(
            client_id,
            program
        )
        # removing the column "visit_data" from the response
        for visit in visits:
            if hasattr(visit, 'visit_data'):
                delattr(visit, 'visit_data')
        return visits

    @tool_schema(ClientInput)
    async def get_visit_questions(
        self,
        client_id: str,
        program: str,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get visit information for a specific store, focusing on questions and answers.
        """
        if program:
            self.program = program
        visits = await self._get_visits(
            client_id,
            program
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
