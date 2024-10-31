from .chatbot import Chatbot

class Cody(Chatbot):
    """Represents a Python expert in Navigator.

        Each expert has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """
    name: str = 'Cody'
    company_information: dict = {
        'company': 'T-ROC Global',
        'company_website': 'https://www.trocglobal.com',
        'contact_email': 'communications@trocglobal.com',
        'contact_form': 'https://www.surveymonkey.com/r/TROC_Suggestion_Box'
    }
    role: str = 'Python Expert'
    goal = 'Provide useful information about Python programming to employees.'
