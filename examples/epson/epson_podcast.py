from typing import List, Optional, Any, Dict, List
import asyncio
from datetime import datetime
from asyncdb.models import Model, Field
from parrot.bots.agent import BasicAgent
from parrot.models.responses import AgentResponse
from parrot.conf import STATIC_DIR
from parrot.tools.abstract import AbstractTool
from parrot.tools.ppt import PowerPointTool
from parrot.tools.pythonpandas import PythonPandasTool


EPSON_PROMPT = """
Your name is $name, an IA Copilot specialized in providing detailed information about Epson products.

$capabilities

**Mission:** Provide all the necessary information about Epson products to assist users in making informed decisions.
**Background:** You are a senior product manager for EPSON.

**Knowledge Base:**
$pre_context
$context

**Conversation History:**
$chat_history

**Instructions:**
Given the above context, available tools, and conversation history, please provide comprehensive and helpful responses. When appropriate, use the available tools to enhance your answers with accurate, up-to-date information or to perform specific tasks.

$rationale

"""

EPSON_PROMOTIONS = """
# Promotions in USA

Retailer's will receive an instant rebate for customers that trade-in a used printer in compliance with Retailer's Trade-in program (as outlined in table below)

## Promotion Date:
April 1, 2023 - March 31, 2025

### Eligible Printers & Epson Funded IR:

* ECOTANK ET-2400
* ECOTANK ET-2800-B
* ECOTANK ET-2800-W
* ECOTANK ET-2850-B
* ECOTANK ET-2850-W
* ECOTANK ET-3830 WHITE AIO PRINTER WIFI
* ECOTANK ET-3850 WHITE AIO PRINTER WIFI
* ECOTANK ET-4850 BLACK AIO PRINTER WIFI
* ECOTANK ET-4850 WHITE AIO PRINTER WIFI
* ECOTANK PRO ET-5150 WHITE PRINTER WIFI
* ECOTANK PRO ET-5170 WHITE WIFI PRINTER
* ECOTANK PRO ET-5180 WHITE WIFI
* ECOTANK ET-5800 AIO PRINTER WIFI
* ECOTANK ET-5850 AIO PRINTER
* ECOTANK ET-5880 AIO PRINTER
* ECOTANK ET-15000 AIO PRINTER
* ECOTANK MONO ET-M1170 SFP PRINTER WIFI
* ECOTANK MONO ET-M2170 AIO PRINTER WIFI
* ECOTANK MONO ET-M3170 AIO PRINTER WIFI
* ECOTANK ET-8500 WHITE AIO PRINTER WIFI
* ECOTANK ET-8550 WHITE AIO PRINTER WIFI
* ECOTANK ET-16600 AIO PRINTER
* ECOTANK ET-16650 AIO PRINTER

## Promotions Table:

| effective\_date    | product\_code | product\_description                   | model     | Epson-Funded IR | Account Contribution | TITU Applicable | Retailer     |
| ------------------ | ------------- | -------------------------------------- | --------- | --------------: | -------------------: | --------------- | ------------ |
| Effective 1/1/2024 | C11CJ67201    | ECOTANK ET-2400                        | ET-2400   |            \$10 |                  \$0 | In-store Only   | Best Buy     |
| Effective 1/1/2024 | C11CJ66201    | ECOTANK ET-2800-B                      | ET-2800-B |            \$20 |                  \$0 | In-store Only   | Staples      |
| Effective 1/1/2024 | C11CJ66202    | ECOTANK ET-2800-W                      | ET-2800-W |            \$20 |                  \$0 | In-store Only   | Office Depot |
|                    | C11CJ63201    | ECOTANK ET-2850-B                      | ET-2850-B |            \$30 |                  \$0 | In-store Only   | Best Buy     |
|                    | C11CJ63202    | ECOTANK ET-2850-W                      | ET-2850-W |            \$30 |                  \$0 | In-store Only   | Staples      |
|                    | C11CJ62201    | ECOTANK ET-3830 WHITE AIO PRINTER WIFI | ET-3830   |            \$30 |                  \$0 | In-store Only   | Office Depot |
|                    | C11CJ61201    | ECOTANK ET-3850 WHITE AIO PRINTER WIFI | ET-3850   |            \$30 |                  \$0 | In-store Only   | Best Buy     |
| Effective 8/1/2024 | C11CJ60201    | ECOTANK ET-4850 BLACK AIO PRINTER WIFI | ET-4850-B |            \$50 |                  \$0 | In-store Only   | Staples      |
| Effective 8/1/2024 | C11CJ60202    | ECOTANK ET-4850 WHITE AIO PRINTER WIFI | ET-4850-W |            \$50 |                  \$0 | In-store Only   | Office Depot |
|                    | C11CJ89201    | ECOTANK PRO ET-5150 WHITE PRINTER WIFI | ET-5150   |            \$50 |                  \$0 | In-store Only   | Best Buy     |
|                    | C11CJ88201    | ECOTANK PRO ET-5170 WHITE WIFI PRINTER | ET-5170   |            \$50 |                  \$0 | In-store Only   | Staples      |
|                    | C11CJ88202    | ECOTANK PRO ET-5180 WHITE WIFI         | ET-5180   |            \$50 |                  \$0 | In-store Only   | Office Depot |
|                    | C11CJ30201    | ECOTANK ET-5800 AIO PRINTER WIFI       | ET-5800   |            \$50 |                  \$0 | In-store Only   | Best Buy     |
|                    | C11CJ29201    | ECOTANK ET-5850 AIO PRINTER            | ET-5850   |            \$50 |                  \$0 | In-store Only   | Staples      |
|                    | C11CJ28201    | ECOTANK ET-5880 AIO PRINTER            | ET-5880   |            \$50 |                  \$0 | In-store Only   | Office Depot |
|                    | C11CH96201    | ECOTANK ET-15000 AIO PRINTER           | ET-15000  |            \$50 |                  \$0 | In-store Only   | Best Buy     |
| Effective 8/1/2024 | C11CH44201    | ECOTANK MONO ET-M1170 SFP PRINTER WIFI | ET-M1170  |            \$50 |                  \$0 | In-store Only   | Staples      |
| Effective 8/1/2024 | C11CH43201    | ECOTANK MONO ET-M2170 AIO PRINTER WIFI | ET-M2170  |            \$50 |                  \$0 | In-store Only   | Office Depot |
| Effective 8/1/2024 | C11CG92201    | ECOTANK MONO ET-M3170 AIO PRINTER WIFI | ET-M3170  |            \$50 |                  \$0 | In-store Only   | Best Buy     |
| Effective 8/1/2024 | C11CJ20201    | ECOTANK ET-8500 WHITE AIO PRINTER WIFI | ET-8500   |           \$100 |                  \$0 | In-store Only   | Staples      |
| Effective 8/1/2024 | C11CJ21201    | ECOTANK ET-8550 WHITE AIO PRINTER WIFI | ET-8550   |           \$100 |                  \$0 | In-store Only   | Office Depot |
| Effective 8/1/2024 | C11CH72201    | ECOTANK ET-16600 AIO PRINTER           | ET-16600  |            \$75 |                  \$0 | In-store Only   | Best Buy     |
| Effective 8/1/2024 | C11CH71201    | ECOTANK ET-16650 AIO PRINTER           | ET-16650  |            \$75 |                  \$0 | In-store Only   | Staples      |


## Offer Terms:
* Ads/signage/messaging must NOT show the lower net price, just “Save extra $30, $50, $75 or $100" (as designated in Terms and Conditions)
* Retailer is responsible for administering the trade-in program and providing standard terms and conditions to End-Users
* Retailers are responsible for disposing of traded-in printers in accordance with all applicable electronics recycling laws and program
* Retailer Trade-in claims are subject to audit by Epson America, Inc.
* No substitutions or extensions. Only one rebate TITU can be claimed per printer purchase. Offer is subject to availability
* Offer is eligible for in-store purchases only. Online purchases are excluded
* Compliance with this program shall not be considered a breach of Epson's UP Policy
* This offer is in acquiescence with Epson's UP Policy
* Epson and its agents have the right to substantiate requests and to reject requests for any reason
* This offer is subject to change at any time without notice
* This offer is void where prohibited or restricted by law
* This offer is stackable with Epson instant rebate offers, excluding any Bundle offer


# Promotions in Canada

## Merch/Channel Marketing | Best Buy Canada

### EcoTank - Online/Digital

* FY25/26 - Ongoing Projector Search/Sponsored Products support
* Evergreen - Trade In/Trade up Offer/Savings
* Jan - Mar 2025 - Back to Business campaign
* Jul - Aug 2025 - New Gen 7 ET Launch
* Aug - Sep 2025 - Back to School Campaign with or w/out promos

### EcoTank - In-store

* Offer/Savings; in-store POS (e.g. tent card)
* Jul - Aug 2025 - New Gen 7 ET Launch -
    * Backlit Endcap Graphic including subhead: "Canada's #1 Selling Supertank Printer"
    * Scan bed POS

### Scanners

* FY25/26 - Search or Sponsored Products support
* Feb - Apr 2025 Tax Time Digital Campaign support
* FY26 Future - Maintain Epson Scanner Exclusivity
    * Update Scanner signage to integrate Shaq & new AI messaging
    * POS Insert Cards & Fact tags for new & current products

### Projectors

* FY25/26 - Ongoing Projector Search/Sponsored Products support
* Aug 2024 - Projector POG sku in/out updates - EX Pro and HC980
* Oct 2025 - Sku in/out new Lifestudio products: Pop Plus, Flex Plus
* Jan 2026 - Update wedge for Grand & Grand Plus (Online skus)

"""

class EpsonResponse(Model):
    """
    EpsonResponse is a model that defines the structure of the response for Epson agents.
    """
    model: Optional[str] = Field(
        default=None,
        description="Model of the Epson product"
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="Unique identifier for the agent that processed the request"
    )
    agent_name: Optional[str] = Field(
        default="Agentic",
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
        """Meta class for EpsonResponse."""
        name = "products_informations"
        schema = "epson"
        strict = True
        frozen = False

class EpsonConcierge(BasicAgent):
    """EpsonConcierge in Navigator.

        Epson Concierge is a specialized agent designed to assist users with queries related to Epson products.
        It leverages the EpsonProductToolkit to fetch detailed product information and provide insights.
    """
    _agent_response = AgentResponse
    speech_context: str = (
        "Report evaluates a specific Epson product based on user queries."
    )
    speech_system_prompt: str = (
        "You are an expert brand ambassador for EPSON."
        " Your task is to create a conversational script about the strengths and weaknesses of a specific Epson product."
    )
    speech_length: int = 20  # Default length for the speech report
    num_speakers: int = 1  # Default number of speakers for the podcast

    def __init__(
        self,
        name: str = 'EpsonConcierge',
        agent_id: str = 'epson_concierge',
        use_llm: str = 'openai',
        llm: str = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            agent_id=agent_id,
            llm=llm,
            use_llm=use_llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            tools=tools,
            **kwargs
        )
        self.system_prompt_template = prompt_template or EPSON_PROMPT
        self._system_prompt_base = system_prompt or ''
        # Register all the tools:
        self.tools = self.default_tools(tools)

    def default_tools(self, tools: List[AbstractTool]) -> List[AbstractTool]:
        """Return the default tools for the agent."""
        new_tools = []
        new_tools.append(
            PythonPandasTool(
                    report_dir=STATIC_DIR.joinpath(self.agent_id, 'documents')
            )
        )
        new_tools.append(
            PowerPointTool(
                output_dir=STATIC_DIR.joinpath(self.agent_id, 'presentations')
            )
        )
        if tools is None:
            return new_tools
        if isinstance(tools, list):
            return new_tools + tools
        if isinstance(tools, AbstractTool):
            return new_tools + [tools]
        raise TypeError(
            f"Expected tools to be a list or an AbstractTool instance, got {type(tools)}"
        )


async def get_agent():
    agent = EpsonConcierge(
        llm='openai',
        model='gpt-4o',
    )
    await agent.configure()
    return agent

async def create_report():
    """Create a report for the agent."""
    # This method can be implemented to generate a report based on the agent's interactions or data.
    agent = await get_agent()
    async with agent:
        result = await agent.speech_report(
            report=EPSON_PROMOTIONS,
            max_lines=30,
            num_speakers=2,
            podcast_instructions="conversation.txt"
        )
        print('Podcast created at:', result)
        # Generate a PowerPoint presentation
        ppt = await agent.generate_presentation(
            content=EPSON_PROMOTIONS,
            filename_prefix='epson_presentation',
            pptx_template="template-epson.pptx",
            title='Epson Product Report',
            company='Epson',
            presenter='AI Assistant'
        )
        print(f"PowerPoint presentation generated: {ppt}")

if __name__ == "__main__":
    asyncio.run(create_report())
