from typing import List
import asyncio
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
    async with agent:
        message, response = await agent.generate_report(
            prompt_file="product_info.txt",
            save=True,
            model="C11CJ29201"
        )
        final_output = response.output
        pdf = await agent.pdf_report(
            title='AI-Generated Express Training Report',
            content=final_output,
            filename_prefix='epson_report'
        )
        print(f"Report generated: {pdf}")
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
        print(f"Podcast generated: {podcast}")



if __name__ == "__main__":
    asyncio.run(create_report())
