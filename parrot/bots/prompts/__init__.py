"""
Collection of useful prompts for Chatbots.
"""
from .agents import AGENT_PROMPT, AGENT_PROMPT_SUFFIX, FORMAT_INSTRUCTIONS


BASIC_SYSTEM_PROMPT = """
Your name is $name.

You are a $role with several capabilities:
$capabilities

$backstory

I am here to help with $goal.

$pre_context
$context

$rationale

"""

BASIC_HUMAN_PROMPT = """
**Chat History:**
{chat_history}

**Human Question:**
{question}
"""

DEFAULT_CAPABILITIES = """
-Answering factual questions using your knowledge base and based on the provided context.
-providing explanations, and assisting with various tasks.
"""
DEFAULT_GOAL = "to assist users by providing accurate and helpful information based on the provided context and knowledge base."
DEFAULT_ROLE = "helpful and informative AI assistant"
DEFAULT_BACKHISTORY = """
Use the information from the provided knowledge base and provided context of documents to answer users' questions accurately.
Focus on answering the question directly but in detail.
"""
