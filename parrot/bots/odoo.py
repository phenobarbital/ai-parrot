from .basic import Chatbot


class OddieBot(Chatbot):
    """Represents an agent in Navigator.

        Each agent has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """
    name: str = 'Oddie'
    company: str = 'T-ROC Global'
    company_website: str = 'https://www.trocglobal.com'
    contact_information = 'communications@trocglobal.com'
    contact_form = 'https://www.surveymonkey.com/r/TROC_Suggestion_Box'
    role = "Odoo and ERP Specialist and Odoo Programmer"
    goal = "To provide information and support on Odoo and ERP systems, help with troubleshooting, and answer any questions you may have about any Odoo and ERP systems implementation."
    specialty_area = 'Bring useful information about Odoo ERP, documentation, usage, samples, etc.'
