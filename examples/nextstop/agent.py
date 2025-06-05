# basic requirements:
import os
from typing import Union, List
import json
import asyncio
# Pydantic:
from pydantic import BaseModel, Field
# Langchain Tools:
from langchain_core.tools import BaseTool, BaseToolkit, StructuredTool, ToolException, Tool
# Parrot Agent
from parrot.bots.agent import BasicAgent
from parrot.llms.vertex import VertexLLM
from parrot.llms.groq import GroqLLM
from parrot.llms.anthropic import AnthropicLLM
from parrot.llms.openai import OpenAILLM

# Function: Agent Creation:
# If use LLama4 with Groq (fastest model)
vertex = VertexLLM(
    model="gemini-2.0-flash-001",
    preset="analytical",
    use_chat=True
)

groq = GroqLLM(
    model="llama-3.1-8b-instant",
    max_tokens=2048
)

openai = OpenAILLM(
    model="gpt-4.1",
    temperature=0.1,
    max_tokens=2048,
    use_chat=True
)

claude = AnthropicLLM(
    model="claude-3-5-sonnet-20240620",
    temperature=0,
    use_tools=True
)

# Visit info Tool:
# Input Models:
class StoreInfoInput(BaseModel):
    """Input schema for store-related operations requiring a Store ID."""
    store_id: str = Field(
        ...,
        description="The unique identifier of the store you want to visit or know about.",
        example="BBY123",
        title="Store ID",
        min_length=1,
        max_length=50
    )
    model_config = {
        "arbitrary_types_allowed": True,
        "extra": "forbid",
        "json_schema_extra": {
            "required": ["store_id"]
        }
    }


class DemographicsInput(BaseModel):
    """Input schema for demographics data extraction from US Census."""
    zipcode: str = Field(
        ...,
        description="The 5-digit ZIP code for which to retrieve demographic information from US Census data.",
        example="90210",
        title="ZIP Code",
        pattern=r"^\d{5}$"
    )
    include_income: bool = Field(
        default=True,
        description="Whether to include household income statistics in the demographic data.",
        title="Include Income Data"
    )
    include_age: bool = Field(
        default=True,
        description="Whether to include age distribution statistics in the demographic data.",
        title="Include Age Distribution"
    )
    model_config = {
        "arbitrary_types_allowed": True,
        "extra": "forbid",
        "json_schema_extra": {
            "required": ["zipcode"]
        }
    }


class StoreInfo(BaseToolkit):
    """Comprehensive toolkit for store information and demographic analysis.

    This toolkit provides tools to:
    1. Get detailed visit information for specific stores including recent visit history
    2. Retrieve comprehensive store information including location and visit statistics
    3. Extract demographic data from US Census for geographic analysis

    All tools are designed to work asynchronously with database connections and external APIs.
    The toolkit is compatible with Langchain agents and supports structured input/output.

    Tools included:
    - get_visit_info: Retrieves the last 3 visits for a specific store
    - get_store_information: Gets complete store details and aggregate visit metrics
    - get_demographics_data: Extracts US Census demographic data by ZIP code
    """

    model_config = {
        "arbitrary_types_allowed": True
    }

    def get_tools(self) -> List[BaseTool]:
        """Get all available tools in the toolkit.

        Returns:
            List[BaseTool]: A list of configured Langchain tools ready for agent use.
        """
        return [
            self._get_visit_info_tool(),
            self._get_store_info_tool(),
            self._get_demographics_tool()
        ]

    def _get_visit_info_tool(self) -> StructuredTool:
        """Create the visit information retrieval tool.

        Returns:
            StructuredTool: Configured tool for getting recent visit data for a store.
        """
        return StructuredTool.from_function(
            name="get_visit_info",
            func=self.get_visit_info,
            coroutine=self.get_visit_info,
            description=(
                "Retrieve the last 3 visits made to a specific store. "
                "Returns detailed information including visit timestamps, duration, "
                "customer types, and visit purposes. Useful for understanding recent "
                "customer activity patterns and store performance."
            ),
            args_schema=StoreInfoInput,
            handle_tool_error=True
        )

    async def get_visit_info(self, store_id: str) -> str:
        """Get visit information for a specific store.

        This coroutine retrieves the most recent 3 visits for the specified store,
        including detailed visit metrics and customer information.

        Args:
            store_id (str): The unique identifier of the store.

        Returns:
            str: JSON string containing the last 3 visits with detailed information.

        Note:
            In production, this will connect to the database using asyncpg.
            Current implementation returns dummy data for development.
        """
        # Simulate async database call
        await asyncio.sleep(0.1)

        # Generate dummy data - replace with actual database query
        dummy_visits = {
            "store_id": store_id,
            "total_recent_visits": 3,
            "data_period": "last_3_visits",
            "visits": [
                {
                    "visit_id": "V001",
                    "timestamp": "2025-06-05T14:30:00Z",
                    "duration_minutes": 45,
                    "customer_type": "returning",
                    "visit_purpose": "purchase",
                    "items_viewed": 8,
                    "purchase_amount": 156.99,
                    "customer_satisfaction": 4.2
                },
                {
                    "visit_id": "V002",
                    "timestamp": "2025-06-05T11:15:00Z",
                    "duration_minutes": 23,
                    "customer_type": "new",
                    "visit_purpose": "browsing",
                    "items_viewed": 12,
                    "purchase_amount": 0.00,
                    "customer_satisfaction": 3.8
                },
                {
                    "visit_id": "V003",
                    "timestamp": "2025-06-04T16:45:00Z",
                    "duration_minutes": 67,
                    "customer_type": "returning",
                    "visit_purpose": "purchase",
                    "items_viewed": 15,
                    "purchase_amount": 298.45,
                    "customer_satisfaction": 4.7
                }
            ],
            "summary": {
                "avg_duration_minutes": 45.0,
                "total_purchase_amount": 455.44,
                "avg_satisfaction": 4.23,
                "conversion_rate": 0.67
            }
        }

        return json.dumps(dummy_visits, indent=2)

    def _get_store_info_tool(self) -> StructuredTool:
        """Create the store information retrieval tool.

        Returns:
            StructuredTool: Configured tool for getting comprehensive store details.
        """
        return StructuredTool.from_function(
            name="get_store_information",
            func=self.get_store_information,
            coroutine=self.get_store_information,
            description=(
                "Get comprehensive store information including location details, "
                "contact information, operating hours, and aggregate visit statistics. "
                "Provides total visits, unique visitors, and average visit duration "
                "for the specified store. Essential for store analysis and planning."
            ),
            args_schema=StoreInfoInput,
            handle_tool_error=True
        )

    async def get_store_information(self, store_id: str) -> str:
        """Get comprehensive store information for a specific store.

        This coroutine retrieves complete store details including location,
        contact information, operating schedule, and aggregate visit metrics.

        Args:
            store_id (str): The unique identifier of the store.

        Returns:
            str: JSON string containing comprehensive store information and visit statistics.

        Note:
            In production, this will connect to the database using asyncpg.
            Current implementation returns dummy data for development.
        """
        # Simulate async database call
        await asyncio.sleep(0.1)
        print(f"DEBUG: Tool called with store_id: {store_id}")

        # Generate dummy data - replace with actual database query
        dummy_store_info = {
            "store_id": store_id,
            "store_name": f"NextStop Location {store_id}",
            "location": {
                "address": "1234 Commerce Street",
                "city": "Beverly Hills",
                "state": "CA",
                "zipcode": "90210",
                "country": "USA",
                "coordinates": {
                    "latitude": 34.0736,
                    "longitude": -118.4004
                }
            },
            "contact": {
                "phone": "+1-555-0123",
                "email": f"{store_id.lower()}@nextstop.com",
                "manager": "Sarah Johnson"
            },
            "operating_hours": {
                "monday": "09:00-21:00",
                "tuesday": "09:00-21:00",
                "wednesday": "09:00-21:00",
                "thursday": "09:00-21:00",
                "friday": "09:00-22:00",
                "saturday": "08:00-22:00",
                "sunday": "10:00-20:00"
            },
            "store_details": {
                "size_sqft": 15000,
                "established": "2019-03-15",
                "store_type": "flagship",
                "departments": ["electronics", "home", "fashion", "groceries"]
            },
            "visit_statistics": {
                "total_visits": 45678,
                "unique_visitors": 28934,
                "average_visit_duration": 42.5,
                "peak_hours": ["11:00-13:00", "17:00-19:00"],
                "busiest_day": "saturday",
                "monthly_growth_rate": 0.12,
                "last_updated": "2025-06-05T12:00:00Z"
            },
            "performance_metrics": {
                "customer_satisfaction": 4.3,
                "conversion_rate": 0.68,
                "avg_basket_size": 87.45,
                "return_customer_rate": 0.73
            }
        }
        print(f"DEBUG: Tool returning: {dummy_store_info}...")  # Add this
        return json.dumps(dummy_store_info, indent=2)

    def _get_demographics_tool(self) -> StructuredTool:
        """Create the US Census demographics data extraction tool.

        Returns:
            StructuredTool: Configured tool for getting demographic data by ZIP code.
        """
        return StructuredTool.from_function(
            name="get_demographics_data",
            func=self.get_demographics_data,
            coroutine=self.get_demographics_data,
            description=(
                "Extract comprehensive demographic data from US Census for a specific "
                "ZIP code area. Provides population statistics, age distribution, "
                "household income data, education levels, and employment information. "
                "Useful for market analysis, customer segmentation, and business planning."
            ),
            args_schema=DemographicsInput,
            handle_tool_error=True
        )

    async def get_demographics_data(
        self,
        zipcode: str,
        include_income: bool = True,
        include_age: bool = True
    ) -> str:
        """Extract demographics data from US Census for a specific ZIP code.

        This coroutine retrieves comprehensive demographic information from US Census
        data sources, including population, income, age, education, and employment statistics.

        Args:
            zipcode (str): The 5-digit ZIP code for demographic analysis.
            include_income (bool): Whether to include household income statistics.
            include_age (bool): Whether to include age distribution data.

        Returns:
            str: JSON string containing comprehensive demographic data for the ZIP code area.

        Note:
            In production, this will connect to US Census API and/or database.
            Current implementation returns dummy data for development.
        """
        # Simulate async API call to US Census
        await asyncio.sleep(0.2)

        # Generate dummy data - replace with actual Census API calls
        dummy_demographics = {
            "zipcode": zipcode,
            "data_source": "US Census Bureau ACS 5-Year Estimates",
            "reference_year": 2023,
            "geographic_area": {
                "name": f"ZIP Code Tabulation Area {zipcode}",
                "total_area_sqmi": 12.45,
                "population_density": 2847.3
            },
            "population": {
                "total_population": 35456,
                "households": 14267,
                "avg_household_size": 2.48,
                "male_population": 17234,
                "female_population": 18222,
                "population_growth_rate": 0.023
            }
        }

        if include_age:
            dummy_demographics["age_distribution"] = {
                "under_18": 0.22,
                "18_to_34": 0.28,
                "35_to_54": 0.31,
                "55_to_74": 0.15,
                "75_and_over": 0.04,
                "median_age": 38.7
            }

        if include_income:
            dummy_demographics["income_statistics"] = {
                "median_household_income": 78450,
                "mean_household_income": 95230,
                "per_capita_income": 42680,
                "below_poverty_line": 0.08,
                "income_distribution": {
                    "under_25k": 0.12,
                    "25k_to_50k": 0.18,
                    "50k_to_75k": 0.24,
                    "75k_to_100k": 0.19,
                    "100k_to_150k": 0.16,
                    "over_150k": 0.11
                }
            }

        # Always include education and employment
        dummy_demographics.update({
            "education": {
                "high_school_or_higher": 0.91,
                "bachelors_or_higher": 0.67,
                "graduate_degree": 0.24
            },
            "employment": {
                "labor_force_participation": 0.72,
                "unemployment_rate": 0.045,
                "major_industries": [
                    "Professional and technical services",
                    "Finance and insurance",
                    "Retail trade",
                    "Healthcare and social assistance"
                ]
            },
            "housing": {
                "homeownership_rate": 0.64,
                "median_home_value": 485000,
                "median_rent": 2150
            }
        })

        return json.dumps(dummy_demographics, indent=2)


# Toolkit for NextStop Copilot:
tools = StoreInfo().get_tools()

async def get_agent(llm):
    """Create and configure a NextStop Copilot agent with store analysis tools.

    Args:
        llm: The language model instance to use for the agent.

    Returns:
        BasicAgent: Configured agent ready for store and demographic analysis.
    """
    agent = BasicAgent(
        name='NextStop Copilot',
        llm=llm,
        tools=tools
    )
    await agent.configure()
    return agent


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(
        get_agent(llm=vertex)
    )
    print("=== NextStop Copilot Agent Ready ===")
    print("Available commands:")
    print("- Ask about store visits: 'What are the recent visits for store BBY123?'")
    print("- Get store information: 'Tell me about store BBY123'")
    print("- Analyze demographics: 'What are the demographics for ZIP code 90210?'")
    print("- Type 'exit', 'quit', or 'bye' to end the session\n")
    query = input(":: Type in your query: \n")
    EXIT_WORDS = ["exit", "quit", "bye"]
    while query not in EXIT_WORDS:
        if query:
            answer, response, result = loop.run_until_complete(
                agent.invoke(query=query)
            )
            print('::: Response: ', response)
            # Show if tools were actually called
            if result.get('intermediate_steps'):
                print('\n::: Tools Used:')
                for step in result['intermediate_steps']:
                    action, observation = step
                    print(f"- {action.tool}: {action.tool_input}")
        query = input(
            "Type in your query: \n"
        )
print("=== Session ended. Goodbye! ===")
