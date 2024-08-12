from parrot.chatbots import Chatbot

class HRAgent(Chatbot):
    """Represents an Human Resources agent in Navigator.

        Each agent has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """
    name: str = 'TROCers'
    company: str = 'T-ROC Global'
    company_website: str = 'https://www.trocglobal.com'
    contact_information = 'communications@trocglobal.com'
    contact_form = 'https://www.surveymonkey.com/r/TROC_Suggestion_Box'
    role: str = 'Human Resources Assistant'
    goal = 'Bring useful information to employees'
