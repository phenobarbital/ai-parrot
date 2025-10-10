from typing import List, Optional, Any, Dict
from asyncdb import AsyncDB
from querysource.conf import default_dsn
from navconfig import BASE_DIR
from ..tools import AbstractTool
from ..tools.products import ProductInfoTool, ProductListTool, ProductResponse
from .agent import BasicAgent
from ..conf import STATIC_DIR
from ..models.responses import AgentResponse


PRODUCT_PROMPT = """
Your name is $name, and your role is to generate detailed product reports.

"""


class ProductReport(BasicAgent):
    """ProductReport is an agent designed to generate detailed product reports using LLMs and various tools."""
    max_tokens: int = 8192
    temperature: float = 0.0
    _agent_response = AgentResponse

    # Speech/Podcast configuration
    speech_context: str = (
        "This report provides detailed product information and analysis for training purposes. "
    )
    speech_system_prompt: str = (
        "You are an expert product analyst. Your task is to create a conversational script about product information and analysis. "
        "Focus on key product features, customer satisfaction, and market insights."
    )
    speech_length: int = 20  # Default length for the speech report
    num_speakers: int = 2  # Cambiar de 1 a 2
    speakers: Dict[str, str] = {
        "interviewer": {
            "name": "Lydia",
            "role": "interviewer",
            "characteristic": "Bright",
            "gender": "female"
        },
        "interviewee": {
            "name": "Steven",
            "role": "interviewee",
            "characteristic": "Informative",
            "gender": "male"
        }
    }

    def __init__(
        self,
        name: str = 'ProductReport',
        agent_id: str = 'product_report',
        use_llm: str = 'openai',
        llm: str = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        static_dir: Optional[Any] = None,
        **kwargs
    ):
        # Store static_dir before calling super().__init__
        self._static_dir = static_dir

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
        self.system_prompt_template = prompt_template or PRODUCT_PROMPT
        self._system_prompt_base = system_prompt or ''

    def _get_default_tools(self, tools: List[AbstractTool]) -> List[AbstractTool]:
        tools = super()._get_default_tools(tools)

        # Build ProductInfoTool with static_dir if configured
        tool_kwargs = {
            'output_dir': STATIC_DIR.joinpath(self.agent_id, 'documents')
        }

        # Use custom static_dir if provided, otherwise uses BASE_DIR by default
        if hasattr(self, '_static_dir') and self._static_dir is not None:
            tool_kwargs['static_dir'] = self._static_dir

        tools.append(ProductInfoTool(**tool_kwargs))
        return tools

    async def create_product_report(self, program_slug: str, models: Optional[List[str]] = None) -> List[ProductResponse]:
        """
        Create product reports for products in a given program/tenant.

        Args:
            program_slug: The program/tenant identifier (e.g., 'hisense')
            models: Optional list of specific models to process. If None, processes all models.

        Returns:
            List of ProductResponse objects with generated reports
        """
        # Get list of products using the tool
        product_list_tool = ProductListTool()
        products = await product_list_tool._execute(program_slug, models)

        if not products:
            if models:
                print(f"No products found for program '{program_slug}' with models: {models}")
            else:
                print(f"No products found for program '{program_slug}'")
            return []

        responses = []
        db = AsyncDB('pg', dsn=default_dsn)

        async with await db.connection() as conn:  # pylint: disable=E1101 # noqa
            async with self:
                for product in products:
                    try:
                        model = product['model']
                        print(f"Processing Product: {model}")

                        # Generate the product report using the prompt
                        _, response = await self.generate_report(
                            prompt_file="product_info.txt",
                            save=True,
                            model=model,
                            program_slug=program_slug
                        )
                        final_output = response.output

                        # Generate PDF report
                        pdf = await self.pdf_report(
                            title=f'AI-Generated Product Report - {model}',
                            content=final_output,
                            filename_prefix=f'product_report_{model}'
                        )
                        print(f"PDF Report generated: {pdf}")

                        # Generate PowerPoint presentation
                        ppt = await self.generate_presentation(
                            content=final_output,
                            filename_prefix=f'product_presentation_{model}',
                            pptx_template="corporate_template.pptx",
                            title=f'Product Report - {model}',
                            company=program_slug.title(),
                            presenter='AI Assistant'
                        )
                        print(f"PowerPoint presentation generated: {ppt}")

                        # Generate podcast script
                        podcast = await self.speech_report(
                            report=final_output,
                            max_lines=self.speech_length,
                            num_speakers=self.num_speakers,
                            podcast_instructions='product_conversation.txt'
                        )
                        print(f"Podcast script generated: {podcast}")

                        # Update response with file paths
                        response.transcript = final_output
                        response.podcast_path = str(podcast.get('podcast_path'))
                        response.document_path = str(ppt.result.get('file_path'))
                        response.pdf_path = str(pdf.result.get('file_path'))
                        response.script_path = str(podcast.get('script_path'))

                        # Convert AgentResponse to Dict and prepare for database
                        response_dict = response.model_dump()
                        # Remove fields that shouldn't be in the database
                        del response_dict['session_id']
                        del response_dict['user_id']
                        del response_dict['turn_id']
                        del response_dict['images']
                        del response_dict['response']

                        # Add program_slug to the response
                        response_dict['program_slug'] = program_slug

                        # Create ProductResponse and save to database
                        try:
                            ProductResponse.Meta.connection = conn
                            ProductResponse.Meta.schema = program_slug
                            product_response = ProductResponse(**response_dict)
                            product_response.model = model
                            product_response.agent_id = self.agent_id
                            product_response.agent_name = self.name

                            print(f"Saving product response for {model}")
                            await product_response.save()
                            print(f"Successfully saved product response for {model}")
                            responses.append(product_response)

                        except Exception as e:
                            print(f"Error saving ProductResponse for {model}: {e}")
                            print(f"Response dict keys: {list(response_dict.keys())}")
                            continue

                    except Exception as e:
                        print(f"Error processing product {product.get('model', 'unknown')}: {e}")
                        continue

        return responses
