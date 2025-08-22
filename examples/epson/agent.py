from typing import List, Optional, Any, Dict, List
import asyncio
from datetime import datetime
from asyncdb import AsyncDB
from asyncdb.models import Model, Field
from querysource.conf import default_dsn
from parrot.bots.agent import BasicAgent
from parrot.models.responses import AIMessage, AgentResponse
from parrot.conf import STATIC_DIR
from parrot.tools.epson import EpsonProductToolkit
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

EPSON_PRODUCTS = """
SELECT COALESCE(NULLIF(p.material, ''), c.modelnumber) AS model from epson.products p
JOIN epson.products_with_attr c ON p.material = c.modelnumber
JOIN epson.customer_satisfaction cs USING (material)
JOIN epson.products_evaluation pe  USING (material )
JOIN epson.products_compliant pc USING (material)
WHERE p.brand = 'Epson' and c.specifications is not null and cs.customer_satisfaction is not null
GROUP BY p.material, c.modelnumber
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
        new_tools.extend(EpsonProductToolkit().get_tools())
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
    # embed_model = {
    #     "model": "thenlper/gte-base",
    #     "model_type": "huggingface"
    # }
    # agent.define_store(
    #     vector_store='postgres',
    #     embedding_model=embed_model,
    #     dsn=default_dsn,
    #     dimension=768,
    #     table='products_information',
    #     schema='epson',
    # )
    await agent.configure()
    return agent

async def create_report():
    """Create a report for the agent."""
    # This method can be implemented to generate a report based on the agent's interactions or data.
    agent = await get_agent()
    # getting all products:
    db = AsyncDB('pg', dsn=default_dsn)
    async with await db.connection() as conn:
        products, error = await conn.query(EPSON_PRODUCTS)

        async with agent:
            for product in products:
                print(f"Product: {product['model']}")
                model = product['model']

                _, response = await agent.generate_report(
                    prompt_file="product_info.txt",
                    save=True,
                    model=model
                )
                final_output = response.output
                pdf = await agent.pdf_report(
                    title='AI-Generated Express Training Report',
                    content=final_output,
                    filename_prefix='epson_report'
                )
                print(
                    f"Report generated: {pdf}"
                )
                # Generate a PowerPoint presentation
                ppt = await agent.generate_presentation(
                    content=final_output,
                    filename_prefix='epson_presentation',
                    pptx_template="template-epson.pptx",
                    title='Epson Product Report',
                    company='Epson',
                    presenter='AI Assistant'
                )
                print(f"PowerPoint presentation generated: {ppt}")
                # -- Generate a podcast script
                podcast = await agent.speech_report(
                    report=final_output,
                    num_speakers=1
                )
                # saving the values to response:
                response.transcript = final_output
                response.podcast_path = str(podcast.get('podcast_path'))
                response.document_path = str(ppt.result.get('file_path'))
                response.pdf_path = str(pdf.result.get('file_path'))
                response.script_path = str(podcast.get('script_path'))
                # Converting AgentResponse to Dict:
                response_dict = response.model_dump()
                del response_dict['session_id']
                del response_dict['user_id']
                del response_dict['turn_id']
                del response_dict['images']
                del response_dict['response']
                try:
                    EpsonResponse.Meta.connection = conn
                    epson_response = EpsonResponse(**response_dict)
                    epson_response.model = model
                    print(epson_response)
                    # saving to the database:
                    await epson_response.save()
                except Exception as e:
                    print(f"Error saving EpsonResponse: {e}")


if __name__ == "__main__":
    asyncio.run(create_report())
