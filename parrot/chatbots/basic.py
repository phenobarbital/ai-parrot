from .abstract import AbstractChatbot


class Chatbot(AbstractChatbot):
    """Represents an Chatbot in Navigator.

        Each Chatbot has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """
