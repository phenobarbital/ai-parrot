import pandas as pd
from navconfig import BASE_DIR
from navigator.handlers.types import AppHandler
# Tasker:
from navigator.background import BackgroundQueue
from navigator_auth import AuthHandler
from parrot.manager import ChatbotManager
from parrot.conf import ENABLE_AZURE_BOT
from parrot.loaders.handlers import DataManagement
from parrot.conf import STATIC_DIR
from parrot.handlers.bots import (
    FeedbackTypeHandler,
    ChatbotFeedbackHandler,
    PromptLibraryManagement,
    ChatbotUsageHandler,
    ChatbotSharingQuestion
)
from settings.settings import (
    NEW_CLIENT_ID,
    NEW_CLIENT_SECRET,
    TROCERS_CLIENT_ID,
    TROCERS_CLIENT_SECRET,
    BOSE_CLIENT_ID,
    BOSE_CLIENT_SECRET,
    ODOO_CLIENT_ID,
    ODOO_CLIENT_SECRET,
    ASKBRETT_CLIENT_ID,
    ASKBRETT_CLIENT_SECRET,
    BOTTROCDEV_CLIENT_ID,
    BOTTROCDEV_CLIENT_SECRET
)
try:
    from azure_teams_bot import AzureBot
    from azure_teams_bot.bots import ChatBot, AgentBot
    AZUREBOT_INSTALLED = True
except ImportError as exc:
    print(exc)
    AZUREBOT_INSTALLED = False

class Main(AppHandler):
    """
    Main App Handler for Parrot Application.
    """
    app_name: str = 'Parrot'
    enable_static: bool = True
    enable_pgpool: bool = True
    staticdir: str = STATIC_DIR

    def configure(self):
        super(Main, self).configure()
        ### Auth System
        # create a new instance of Auth System
        auth = AuthHandler()
        auth.setup(self.app)
        # Tasker: Background Task Manager:
        tasker = BackgroundQueue(
            app=self.app,
            max_workers=5,
            queue_size=5
        )
        # Chatbot System
        self.chatbot_manager = ChatbotManager()
        self.chatbot_manager.setup(self.app)

        # API of feedback types:
        self.app.router.add_view(
            '/api/v1/feedback_types/{feedback_type}',
            FeedbackTypeHandler
        )
        ChatbotFeedbackHandler.configure(self.app, '/api/v1/bot_feedback')
        # Prompt Library:
        PromptLibraryManagement.configure(self.app, '/api/v1/chatbots/prompt_library')
        # Questions (Usage handler, for sharing)
        ChatbotUsageHandler.configure(self.app, '/api/v1/chatbots/usage')
        self.app.router.add_view(
            '/api/v1/chatbots/questions/{sid}',
            ChatbotSharingQuestion
        )
        # Management APIs:
        DataManagement.configure(self.app)

        # Azure Bot:
        if ENABLE_AZURE_BOT and AZUREBOT_INSTALLED:
            # Lucas Bot:
            chat = ChatBot(
                app=self.app,
                # bot=self.hr_agent,
                bot_name='TROCers',
                welcome_message='Welcome to TROCers Bot, you can ask me anything about T-ROC.'
            )
            AzureBot(
                app=self.app,
                bots=[chat],
                route='/api/edu/messages',
                client_id=TROCERS_CLIENT_ID,
                secret_id=TROCERS_CLIENT_SECRET
            )
            # Odoo Bot:
            # odoo = ChatBot(
            #     app=self.app,
            #     bot_name='Oddie',
            #     welcome_message='Welcome to Odoo Bot, you can ask me anything about Odoo ERP.'
            # )
            # AzureBot(
            #     app=self.app,
            #     bots=[odoo],
            #     client_id=ODOO_CLIENT_ID,
            #     secret_id=ODOO_CLIENT_SECRET,
            #     route='/api/oddie/messages'
            # )
            # # Odoo Dev Bot:
            # AzureBot(
            #     app=self.app,
            #     bots=[odoo],
            #     client_id=BOTTROCDEV_CLIENT_ID,
            #     secret_id=BOTTROCDEV_CLIENT_SECRET,
            #     route='/api/oddiedev/messages'
            # )
            # Ask Brett (now askTROC):
            brett = ChatBot(
                app=self.app,
                bot_name='AskTROC',
                welcome_message=(
                    "Welcome to the T-ROC BOT. May name is TROCer, you can ask me anything about T-ROC."
                    "About T-ROC Clients, Case studies, success stories, and more."
                )
            )
            AzureBot(
                app=self.app,
                bots=[brett],
                client_id=ASKBRETT_CLIENT_ID,
                secret_id=ASKBRETT_CLIENT_SECRET,
                route='/api/askbrett/messages'
            )
            # Bose Bot:
            bose = ChatBot(
                app=self.app,
                bot_name='BoseBot',
                welcome_message=(
                    'Welcome to Bose Bot, you can ask me anything about Bose Systems.'
                    'Installations, displays, services, troubleshooting, etc.'
                )
            )
            AzureBot(
                app=self.app,
                bots=[bose],
                client_id=BOSE_CLIENT_ID,
                secret_id=BOSE_CLIENT_SECRET,
                route='/api/bose/messages'
            )
            # Agent:
            paywhiz = AgentBot(
                app=self.app,
                bot_name='PayWhiz',
                welcome_message='Welcome to PayWhiz Bot, you can ask me anything about Payroll.',
                file=BASE_DIR.joinpath('docs', 'agent', 'payroll_employees_2024-06-18.xlsx')
            )
            AzureBot(
                app=self.app,
                bots=[paywhiz],
                client_id=BOTTROCDEV_CLIENT_ID,
                secret_id=BOTTROCDEV_CLIENT_SECRET,
                route='/api/paywhiz/messages'
            )

    async def on_prepare(self, request, response):
        """
        on_prepare.
        description: Signal for customize the response while is prepared.
        """

    async def pre_cleanup(self, app):
        """
        pre_cleanup.
        description: Signal for running tasks before on_cleanup/shutdown App.
        """

    async def on_cleanup(self, app):
        """
        on_cleanup.
        description: Signal for customize the response when server is closing
        """

    async def on_startup(self, app):
        """
        on_startup.
        description: Signal for customize the response when server is started
        """
        app['websockets'] = []

    async def on_shutdown(self, app):
        """
        on_shutdown.
        description: Signal for customize the response when server is shutting down
        """
        pass
