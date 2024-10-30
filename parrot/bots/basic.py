from .abstract import AbstractChatbot


class BasicBot(AbstractChatbot):
    """Represents an BasicBot in Navigator.

        Each BasicBot has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """
    pass

class Chatbot(AbstractChatbot):
    """Represents an Chatbot in Navigator.

        Each Chatbot has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """
    template_prompt: str = (
        "You are {name}, an expert AI assistant and {role} Working at {company}.\n\n"
        "Your primary function is to {goal}\n"
        "Use the provided context of the documents you have processed or extracted from other provided tools or sources to provide informative, detailed and accurate responses.\n"
        "I am here to help with {role}.\n"
        "**Backstory:**\n"
        "{backstory}.\n\n"
        "Focus on answering the question directly but detailed. Do not include an introduction or greeting in your response.\n\n"
        "Here is a brief summary of relevant information:\n"
        "Context: {context}\n\n"
        "Given this information, please provide answers to the following question adding detailed and useful insights:\n\n"
        "**Chat History:** {chat_history}\n\n"
        "**Human Question:** {question}\n"
        "Assistant Answer:\n\n"
        "{rationale}\n"
        "You are a fluent speaker, you can talk and respond fluently in English and Spanish, and you must answer in the same language as the user's question. If the user's language is not English, you should translate your response into their language.\n"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Company Information:
        self.company_information: dict = kwargs.pop('company_information', {})


    def __repr__(self):
        return f"<ChatBot.{self.__class__.__name__}:{self.name}>"

    def default_backstory(self) -> str:
        return (
            "help with Human Resources related queries or knowledge-based questions about T-ROC Global.\n"
            "You can ask me about the company's products and services, the company's culture, the company's clients.\n"
            "You have the capability to read and understand various Human Resources documents, "
            "such as employee handbooks, policy documents, onboarding materials, company's website, and more.\n"
            "I can also provide information about the company's policies and procedures, benefits, and other HR-related topics."
        )

    def default_rationale(self) -> str:
        return (
            "I am a large language model (LLM) trained by Google.\n"
            "I am designed to provide helpful information to users."
            "Remember to maintain a professional tone."
            "If I cannot find relevant information in the documents,"
            "I will indicate this and suggest alternative avenues for the user to find an answer."
        )
