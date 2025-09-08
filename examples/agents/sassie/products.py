from typing import List, Optional, Any, Dict, List
import asyncio
from datetime import datetime
from asyncdb import AsyncDB
from asyncdb.models import Model, Field
from querysource.conf import default_dsn
from parrot.bots.sassie import SassieAgent

SASSIE_PRODUCTS = """
SELECT p.model, p.model_code from google.products p
JOIN google.customer_satisfaction cs USING (sku)
JOIN google.products_evaluation pe  USING (sku)
JOIN google.products_compliant pc USING (sku)
WHERE p.brand = 'Google'  and p.specifications is not null and cs.customer_satisfaction is not null
AND p.model = 'Pixel 10 Pro XL'
GROUP BY p.model, p.model_code

"""


class SassieResponse(Model):
    """
    SassieResponse is a model that defines the structure of the response for Sassie agents.
    """
    model: Optional[str] = Field(
        default=None,
        description="Model of the Sassie product"
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
        """Meta class for SassieResponse."""
        name = "products_informations"
        schema = "sassie"
        strict = True
        frozen = False


async def get_agent():
    agent = SassieAgent(
        llm='openai',
        model='gpt-4o',
    )
    await agent.configure()
    return agent

async def create_report():
    """Create a report for the agent."""
    # This method can be implemented to generate a report based on the agent's interactions or data.
    agent = await get_agent()
    # getting all products:
    db = AsyncDB('pg', dsn=default_dsn)
    async with await db.connection() as conn:
        products, error = await conn.query(SASSIE_PRODUCTS)

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
                    filename_prefix='sassie_product_report'
                )
                print(
                    f"Report generated: {pdf}"
                )
                # Generate a PowerPoint presentation
                ppt = await agent.generate_presentation(
                    content=final_output,
                    filename_prefix='sassie_product_presentation',
                    pptx_template="template-google.pptx",
                    title='Sassie Product Report',
                    company='Google',
                    presenter='AI Assistant'
                )
                print(f"PowerPoint presentation generated: {ppt}")
                # -- Generate a podcast script
                podcast = await agent.speech_report(
                    report=final_output,
                    num_speakers=1,
                    podcast_instructions='product_conversation.txt'
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
                    SassieResponse.Meta.connection = conn
                    sassie_response = SassieResponse(**response_dict)
                    sassie_response.model = model
                    print(sassie_response)
                    # saving to the database:
                    await sassie_response.save()
                except Exception as e:
                    print(f"Error saving SassieResponse: {e}")


if __name__ == "__main__":
    asyncio.run(create_report())
