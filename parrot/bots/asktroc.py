from .chatbot import Chatbot

class AskTROC(Chatbot):
    """Represents an Human Resources agent in Navigator.

        Each agent has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """
    company_information: dict = {
        'company': 'T-ROC Global',
        'company_website': 'https://www.trocglobal.com',
        'contact_email': 'communications@trocglobal.com',
        'contact_form': 'https://www.surveymonkey.com/r/TROC_Suggestion_Box'
    }
    role: str = 'Expert T-ROCer'
    goal = 'Bring useful information about T-ROC Global to employees.'
