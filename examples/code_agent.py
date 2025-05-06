import pandas as pd
from langchain.globals import set_debug, set_verbose
from langchain_experimental.agents import create_pandas_dataframe_agent
from langchain_experimental.tools import PythonREPLTool
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from parrot.llms.vertex import VertexLLM
from parrot.llms.google import GoogleGenAI

# Enable verbosity for debugging
set_debug(True)
set_verbose(True)

# Initialize the Gemini1.5 Pro model from Vertex AI
llm = VertexLLM(
    model='gemini-1.5-pro',
    temperature=0.1,
    top_k=30,
    top_p=0.5,
    use_chat=True
)

llm = GoogleGenAI(
    model='gemini-1.5-pro',
    temperature=0.1,
    top_k=30,
    top_p=0.5,
    use_chat=True
)
# Create a sample DataFrame
data = {
    "Name": ["John", "Anna", "Peter", "Linda"],
    "Age": [28,24,35,32],
    "City": ["New York", "Paris", "Berlin", "London"]
}
df = pd.DataFrame(data)

# Create the Python REPL tool with locals dictionary including the dataframe
python_locals = {"df": df}
python_tool = PythonAstREPLTool(locals=python_locals)

# Create the Pandas DataFrame agent with the extra tools
agent_executor = create_pandas_dataframe_agent(
    llm.get_llm(),
    [df],
    agent_type="tool-calling",
    verbose=True,
    allow_dangerous_code=True, # Be cautious with this setting
    # extra_tools=[python_tool],
    return_intermediate_steps=True,
    agent_executor_kwargs={"handle_parsing_errors": True} # Good practice
)

# Example usage
query = "What is the average age of people in the DataFrame?"
result = agent_executor.invoke({"input": query})
print(result)
