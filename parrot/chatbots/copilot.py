from langchain_experimental.tools.python.tool import PythonAstREPLTool
from .base import BaseAgent
# importing Tools
from ..tools import (
    ZipcodeAPIToolkit,
    WikipediaTool,
    WikidataTool,
    GoogleSearchTool,
    GoogleLocationFinder,
    BingSearchTool,
    AskNewsTool,
    DuckDuckGoSearchTool,
    YouTubeSearchTool,
    OpenWeatherMapTool,
    StackExchangeTool,
)


class CopilotAgent(BaseAgent):
    """CopilotAgent Agent.

    This is Agent Base class for AI Copilots.
    """
    def __init__(
        self,
        name: str = 'Agent',
        llm: str = 'vertexai',
        tools: list = None,
        prompt_template: str = None,
        **kwargs
    ):
        super().__init__(name, llm, tools, prompt_template, **kwargs)
        self.tools = [
                PythonAstREPLTool(
                    name='python_repl_ast',
                    globals={},
                    locals={}
                )
            ] + list(tools)
        self.prompt = self.get_prompt(
            self.prompt_template
        )
        # print('PROMPT > ', self.prompt)

    @classmethod
    def default_tools(cls) -> list:
        # ZipCode API Toolkit
        tools = []
        zpt_tools = []
        try:
            zpt = ZipcodeAPIToolkit()
            zpt_tools = zpt.get_tools()

        except Exception as e:
            print('ERROR LOADING ZIPCODE TOOLS')

        try:
            wk1 = WikipediaTool()
            wk12 = WikidataTool()

            g1 = GoogleSearchTool()
            g2 = GoogleLocationFinder()

            b = BingSearchTool()
            d = DuckDuckGoSearchTool()
            ask = AskNewsTool()

            yt = YouTubeSearchTool()
            stackexchange = StackExchangeTool()
            weather = OpenWeatherMapTool()

            tools = [
                wk1,
                wk12, g1, g2,
                b, d, ask, yt,
                weather,
                stackexchange
            ] + zpt_tools

        except Exception as e:
            print('TOOL Error > ', e)

        return tools
