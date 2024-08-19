from abc import ABC
from typing import Any
from aiohttp import web
# Langchain:
from langchain_core.prompts import (
    PromptTemplate,
    ChatPromptTemplate
)
from langchain.agents.agent import (
    AgentExecutor,
    RunnableAgent,
    RunnableMultiActionAgent,
)
from langchain.memory import (
    ConversationBufferMemory
)
from langchain.agents import create_react_agent
from langchain_community.chat_message_histories import (
    RedisChatMessageHistory
)
from navconfig.logging import logging
## LLM configuration
# Vertex
try:
    from ..llms.vertex import VertexLLM
    VERTEX_ENABLED = True
except (ModuleNotFoundError, ImportError):
    VERTEX_ENABLED = False

# Google
try:
    from ..llms.google import GoogleGenAI
    GOOGLE_ENABLED = True
except (ModuleNotFoundError, ImportError):
    GOOGLE_ENABLED = False

# Anthropic:
try:
    from ..llms.anthropic import Anthropic
    ANTHROPIC_ENABLED = True
except (ModuleNotFoundError, ImportError):
    ANTHROPIC_ENABLED = False

# OpenAI
try:
    from ..llms.openai import OpenAILLM
    OPENAI_ENABLED = True
except (ModuleNotFoundError, ImportError):
    OPENAI_ENABLED = False

# Groq
try:
    from ..llms.groq import GroqLLM
    GROQ_ENABLED = True
except (ModuleNotFoundError, ImportError):
    GROQ_ENABLED = False

from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
)  # for exponential backoff
from ..interfaces import DBInterface
from ..models import AgentResponse
from ..conf import REDIS_HISTORY_URL


BASEPROMPT = """
Your name is {name}. You are a helpful and advanced AI assistant equipped with various tools to help users find information and solve problems efficiently.
You are designed to be able to assist with a wide range of tasks.
Overall, Assistant is a powerful tool that can help with a wide range of tasks and provide valuable insights and information on a wide range of topics.
Whether you need help with a specific question or just want to have a conversation about a particular topic, Assistant is here to assist.

**Has access to the following tools:**

- {tools}
- Google Web Search: Perform web searches to retrieve the latest and most relevant information from the internet.
- google_maps_location_finder: Find location information, including latitude, longitude, and other geographical details.
- Wikipedia: Access detailed and verified information from Wikipedia.
- WikiData: Fetch structured data from WikiData for precise and factual details.
- Bing Search: Search the web using Microsoft Bing Search, conduct searches using Bing for alternative perspectives and sources.
- DuckDuckGo Web Search: Search the web using DuckDuckGo Search.
- zipcode_distance: Calculate the distance between two zip codes.
- zipcode_location: Obtain geographical information about a specific zip code.
- zipcodes_by_radius: Find all US zip codes within a given radius of a zip code.
- asknews_search: Search for up-to-date news and historical news on AskNews site.
- StackExchangeSearch: Search for questions and answers on Stack Exchange.
- openweather_tool: Get current weather conditions based on specific location, providing latitude and longitude.
- OpenWeatherMap: Get weather information about a location.
- yahoo_finance_news: Retrieve the latest financial news from Yahoo Finance.
- python_repl_ast: A Python shell. Use this to execute python commands. Input should be a valid python command. When using this tool, sometimes output is abbreviated - make sure it does not look abbreviated before using it in your answer.
- youtube_search: Search for videos on YouTube based on specific keywords.


Use these tools effectively to provide accurate and comprehensive responses.

**Instructions:**
1. Understand the Query: Comprehend the user's request, especially if it pertains to events that may have already happened.
2. **Event Timing Validation**: For questions about recent events or events that may have happened already (like sporting events, conferences, etc.), if you're not confident that the event has happened, you must **use one of the web search tools** to confirm before making any conclusions.
3. Determine Confidence: If confident (90%+), provide the answer directly within the Thought process. If not confident, **always use a web search tool**.
4. Choose Tool: If needed, select the most suitable tool, using one of [{tool_names}].
5. Collect Information: Use the tool to gather data.
6. Analyze Information: Identify patterns, relationships, and insights.
7. Synthesize Response: Combine the information into a clear response.
8. Cite Sources: Mention the sources of the information.

** Your Style: **
- Maintain a professional and friendly tone.
- Be clear and concise in your explanations.
- Use simple language for complex topics to ensure user understanding.

To respond directly, use the following format:
```
Question: the input question you must answer.
Thought: Explain your reasoning.
Final Thought: Summarize your findings.
Final Answer: Provide a clear and structured answer to the original question with relevant details.
```


To use a tool, please use the following format:
```
Question: the input question you must answer.
Thought: Explain your reasoning, including whether you need to use a tool.
Action: the action to take, should be one of [{tool_names}].
- If using a tool: Specify the tool name (e.g., "Google Web Search") and the input.
Action Input: the input to the action.
Observation: the result of the action.
... (this Thought/Action/Action Input/Observation can repeat N times)
Final Thought: Summarize your findings.
Final Answer: Provide a clear and structured answer to the original question with relevant details.
Detailed Result: Include the detailed result from the tool here if applicable.
```

**Important**: For recent events (such as the Paris 2024 Olympic Games), you must **use a web search tool** to verify the outcome or provide accurate up-to-date information before concluding. Always prioritize using tools if you're unsure or if the event is recent.


Begin!

Question: {input}
{agent_scratchpad}
"""

class BaseAgent(ABC, DBInterface):
    """Base Agent Interface.

    This is the base class for all Agent Chatbots. It is an abstract class that
    must be implemented by all Agent Chatbots.

    """
    def __init__(
        self,
        name: str = 'Agent',
        llm: str = 'vertexai',
        tools: list = None,
        prompt_template: str = None,
        **kwargs
    ):
        self.name = name
        self.tools = tools
        self.prompt_template = prompt_template
        if not self.prompt_template:
            self.prompt_template = BASEPROMPT
        self.llm = self.llm_chain(llm, **kwargs)
        self.prompt = self.get_prompt(self.prompt_template)
        self.kwargs = kwargs
        # Bot:
        self._agent = None
        self.agent = None
        # Logger:
        self.logger = logging.getLogger('Parrot.Agent')

    def get_prompt(self, prompt, **kwargs):
        partial_prompt = ChatPromptTemplate.from_template(prompt)
        return partial_prompt.partial(
            tools=self.tools,
            name=self.name,
            **kwargs
        )

    def get_memory(
        self,
        session_id: str = None,
        key: str = 'chat_history',
        input_key: str = 'question',
        output_key: str = 'answer',
        size: int = 5,
        ttl: int = 86400
    ):
        args = {
            'memory_key': key,
            'input_key': input_key,
            'output_key': output_key,
            'return_messages': True,
            'max_len': size
        }
        if session_id:
            message_history = RedisChatMessageHistory(
                url=REDIS_HISTORY_URL,
                session_id=session_id,
                ttl=ttl
            )
            args['chat_memory'] = message_history
        return ConversationBufferMemory(
            **args
        )

    def create_agent(self, **kwargs):
        # Create a ReAct Agent:
        self.agent = RunnableAgent(
            runnable = create_react_agent(
                self.llm,
                self.tools,
                prompt=self.prompt,
            ),  # type: ignore
            input_keys_arg=["input"],
            return_keys_arg=["output"],
        )
        return self.agent

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
    def llm_chain(
        self, llm: str = "vertexai", **kwargs
    ):
        """llm_chain.

        Args:
            llm (str): The language model to use.

        Returns:
            str: The language model to use.

        """
        if llm == 'openai':
            mdl = OpenAILLM(model="gpt-3.5-turbo", **kwargs)
        elif llm in ('vertexai', 'VertexLLM'):
            mdl = VertexLLM(model="gemini-1.5-pro", **kwargs)
        elif llm == 'anthropic':
            mdl = Anthropic(model="claude-3-opus-20240229", **kwargs)
        elif llm in ('groq', 'Groq', 'llama3'):
            mdl = GroqLLM(model="llama3-70b-8192", **kwargs)
        elif llm == 'mixtral':
            mdl = GroqLLM(model="mixtral-8x7b-32768", **kwargs)
        elif llm == 'google':
            mdl = GoogleGenAI(model="models/gemini-1.5-pro-latest", **kwargs)
        else:
            raise ValueError(f"Invalid llm: {llm}")

        # get the LLM:
        return mdl.get_llm()

    def get_executor(self, agent: RunnableAgent, tools: list, verbose: bool = True):
        return AgentExecutor(
            agent=agent,
            tools=tools,
            # callback_manager=callback_manager,
            verbose=verbose,
            return_intermediate_steps=True,
            max_iterations=5,
            max_execution_time=360,
            handle_parsing_errors=True,
            # memory=self.memory,
            # early_stopping_method='generate',
            **(self.kwargs or {}),
        )

    def get_chatbot(self):
        return self.get_executor(self.agent, self.tools)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._agent = None

    def get_conversation(self):
        # Create the agent:
        self.create_agent()
        # define conversation:
        self._agent = self.get_chatbot()
        return self

    def get_retrieval(self, request: web.Request) -> Any:
        # Create the agent:
        self.create_agent()
        # define conversation:
        self._agent = self.get_chatbot()
        self.request = request
        return self

    async def question(
            self,
            question: str = None,
            chain_type: str = 'stuff',
            search_type: str = 'similarity',
            search_kwargs: dict = {"k": 4, "fetch_k": 10, "lambda_mult": 0.89},
            return_docs: bool = True,
            metric_type: str = None,
            memory: Any = None,
            **kwargs
    ):
        """question.

        Args:
            question (str): The question to ask the chatbot.
            chain_type (str): The type of chain to use.
            search_type (str): The type of search to use.
            search_kwargs (dict): The search kwargs to use.
            return_docs (bool): Return the documents.
            metric_type (str): The metric type to use.
            memory (Any): The memory to use.

        Returns:
            Any: The response from the chatbot.

        """
        # TODO: adding the vector-search to the agent
        input_question = {
            "input": question
        }
        result = self._agent.invoke(input_question)
        try:
            response = AgentResponse(question=question, **result)
            response.response = self.as_markdown(
                response
            )
            return response
        except Exception as e:
            self.logger.exception(
                f"Error on response: {e}"
            )
            raise

    def invoke(self, query: str):
        """invoke.

        Args:
            query (str): The query to ask the chatbot.

        Returns:
            str: The response from the chatbot.

        """
        input_question = {
            "input": query
        }
        result = self._agent.invoke(input_question)
        try:
            response = AgentResponse(question=query, **result)
            try:
                return self.as_markdown(
                    response
                ), response
            except Exception as exc:
                self.logger.exception(
                    f"Error on response: {exc}"
                )
                return result.get('output', None), None
        except Exception as e:
            return result, e

    def as_markdown(self, response: AgentResponse) -> str:
        markdown_output = f"**Question**: {response.question}  \n"
        markdown_output += f"**Answer**: {response.output}  \n"
        markdown_output += "```"
        return markdown_output
