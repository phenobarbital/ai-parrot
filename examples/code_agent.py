from typing_extensions import Annotated, TypedDict
import pandas as pd
from langchain.globals import set_debug, set_verbose
from langchain.memory import (
    ConversationBufferWindowMemory
)
from langchain_experimental.agents import create_pandas_dataframe_agent
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from langchain_core.messages import HumanMessage
from parrot.llms.vertex import VertexLLM
from parrot.llms.groq import GroqLLM
from parrot.llms.anthropic import AnthropicLLM
from parrot.llms.google import GoogleGenAI
from parrot.llms.openai import OpenAILLM
from parrot.llms.gemma import GemmaLLM


# Enable verbosity for debugging
set_debug(True)
set_verbose(True)

# Initialize the Gemini1.5 Pro model from Vertex AI
vertex = VertexLLM(
    model="gemini-2.0-flash-001",
    temperature=0.1,
    use_chat=True
)

groq = GroqLLM(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    temperature=0.1,
)

claude = AnthropicLLM(
    model="claude-3-5-sonnet-20240620",
    temperature=0.1,
    use_tools=True
)

google = GoogleGenAI(
    model="gemini-2.0-flash-001",
    temperature=0.1,
    use_chat=True
)

openai = OpenAILLM(
    model="gpt-4.1",
    temperature=0.1,
    use_chat=True
)

# Specific LLMs:
gemma = GemmaLLM(
    temperature=0.1,
    top_k=30,
    top_p=0.5
)

# LLama3 instant
llama3 = GroqLLM(
    model="llama-3.1-8b-instant",
    temperature=0.1,
)

# Create a sample DataFrame
data = {
    "Name": ["John", "Anna", "Peter", "Linda"],
    "Age": [28,24,35,32],
    "City": ["New York", "Paris", "Berlin", "London"]
}
df = pd.DataFrame(data)


def multiply_numbers(a: int, b: int) -> int:
    """Multiply two integers.

    Args:
        a: First integer
        b: Second integer
    """
    return a * b

class multiply(TypedDict):
    """Multiply two integers."""

    a: Annotated[int, ..., "First integer"]
    b: Annotated[int, ..., "Second integer"]

# Create the Python REPL tool with locals dictionary including the dataframe
python_locals = {"df": df}
python_tool = PythonAstREPLTool(locals=python_locals, verbose=True,)

# Test with VertexAI
# llm = vertex.get_llm()

# # Test with Groq
# llm = groq.get_llm()

# # Test with Anthropic
llm = claude.get_llm()

# # Test with Google
# llm = google.get_llm()

# # Test with OpenAI
# llm = openai.get_llm()

# Gemma:
# llm = gemma.get_llm()

# # Llama3:
# llm = llama3.get_llm()

# Bind the tools to the LLM
llm_with_tools = llm.bind_tools([python_tool, multiply_numbers])

memory = ConversationBufferWindowMemory(
    memory_key="chat_history",
    k=5,
    return_messages=True,
    input_key="input",
    output_key="output",
)

# Create the Pandas DataFrame agent with the extra tools
agent_executor = create_pandas_dataframe_agent(
    llm_with_tools,
    df,
    agent_type="tool-calling",
    verbose=True,
    allow_dangerous_code=True,
    # extra_tools=[python_tool],
    return_intermediate_steps=True,
    agent_executor_kwargs={"memory": memory, "handle_parsing_errors": True} # Good practice
)

# Example usage
query = "What is the average age of people in the DataFrame?"
# Start the conversation history
messages = [HumanMessage(content=query)]
result = agent_executor.invoke({"input": query})
print(result)
