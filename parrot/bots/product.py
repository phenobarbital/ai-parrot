from typing import List
from ..tools import AbstractTool
from ..tools.products import ProductInfoTool
from .agent import BasicAgent
from ..conf import STATIC_DIR


PRODUCT_PROMPT = """
Your name is $name, and your role is to generate detailed product reports.

"""


class ProductReport(BasicAgent):
    """ProductReport is an agent designed to generate detailed product reports using LLMs and various tools."""
    max_tokens: int = 8192
    temperature: float = 0.0

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
        self.system_prompt_template = prompt_template or PRODUCT_PROMPT
        self._system_prompt_base = system_prompt or ''
        self.tools = self.default_tools(tools)

    def default_tools(self, tools: List[AbstractTool]) -> List[AbstractTool]:
        tools = super().default_tools(tools)
        tools.append(
            ProductInfoTool(
                output_dir=STATIC_DIR.joinpath(self.agent_id, 'documents')
            )
        )
        return tools
