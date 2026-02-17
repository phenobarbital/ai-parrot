from datetime import datetime

from asyncdb import AsyncDB
from asyncdb.exceptions import NoDataFound
from navigator.views import (
    BaseHandler,
    ModelView,
    BaseView,
    FormModel
)
from navigator.views.abstract import AbstractModel
from navigator_auth.decorators import user_session
from parrot.conf import (
    BIGQUERY_CREDENTIALS,
    BIGQUERY_PROJECT_ID,
)
from .models import (
    BotModel,
    ChatbotUsage,
    PromptLibrary,
    ChatbotFeedback,
    FeedbackType
)
from ..tools.abstract import ToolRegistry
from ..registry.registry import BotConfig


class PromptLibraryManagement(ModelView):
    """
    PromptLibraryManagement.
    description: PromptLibraryManagement for Parrot Application.
    """

    model = PromptLibrary
    name: str = "Prompt Library Management"
    path: str = '/api/v1/prompt_library'
    pk: str = 'prompt_id'

    async def _set_created_by(self, value, column, data):
        if not value:
            return await self.get_userid(session=self._session)
        return value


class ChatbotUsageHandler(ModelView):
    """
    ChatbotUsageHandler.
    description: ChatbotUsageHandler for Parrot Application.
    """

    model = ChatbotUsage
    driver: str = 'bigquery'
    name: str = "Chatbot Usage"
    path: str = '/api/v1/chatbots_usage'
    pk: str = 'sid'

    def get_connection(self):
        params = {
            "credentials": BIGQUERY_CREDENTIALS,
            "project_id": BIGQUERY_PROJECT_ID,
        }
        return AsyncDB(
            'bigquery',
            params=params,
            force_closing=False
        )

    async def post(self):
        # Try to use validator when available (as in FormModel); otherwise parse JSON.
        usage = None
        if hasattr(self, 'validate_payload'):
            usage = await self.validate_payload()
        if usage is None:
            try:
                payload = await self.request.json()
            except Exception:
                payload = None
            if not payload:
                return self.error(
                    response={
                        "message": "Error on Chatbot Usage payload"
                    },
                    status=400
                )
            try:
                usage = ChatbotUsage(**payload)
            except Exception as exc:
                return self.error(
                    response={
                        "message": f"Invalid Chatbot Usage payload: {exc}"
                    },
                    status=400
                )

        db = self.get_connection()
        try:
            async with await db.connection() as conn:  #pylint: disable=E1101
                data = usage.to_dict()
                # Normalize types for BigQuery
                if 'sid' in data:
                    data['sid'] = str(data['sid'])
                if 'chatbot_id' in data:
                    data['chatbot_id'] = str(data['chatbot_id'])
                if 'event_timestamp' in data:
                    data['event_timestamp'] = str(data['event_timestamp'])

                # Enrich from request context if missing
                if not data.get('origin'):
                    data['origin'] = getattr(self.request, 'remote', None)
                if not data.get('user_agent'):
                    data['user_agent'] = self.request.headers.get('User-Agent', '')
                if not data.get('user_id'):
                    try:
                        data['user_id'] = await self.get_userid(session=self._session)
                    except Exception:
                        pass

                # Ensure _at exists (sid:used_at)
                if not data.get('_at') and data.get('sid') and data.get('used_at'):
                    data['_at'] = f"{data['sid']}:{data['used_at']}"

                await conn.write(
                    [data],
                    table_id=ChatbotUsage.Meta.name,
                    dataset_id=ChatbotUsage.Meta.schema,
                    use_streams=False,
                    use_pandas=False
                )
                return self.json_response({
                    "message": "Chatbot Usage recorded.",
                    "question": data.get('question'),
                    "sid": data.get('sid')
                }, status=201)
        except Exception as e:
            return self.error(
                response={
                    "message": f"Error on Chatbot Usage: {e}"
                },
                status=400
            )


class ChatbotSharingQuestion(BaseView):
    """
    ChatbotSharingQuestion.
    description: ChatbotSharingQuestion for Parrot Application.
    """

    def get_connection(self):
        params = {
            "credentials": BIGQUERY_CREDENTIALS,
            "project_id": BIGQUERY_PROJECT_ID,
        }
        return AsyncDB(
            'bigquery',
            params=params
        )

    async def get(self):
        qs = self.get_arguments(self.request)
        sid = qs.get('sid', None)
        if not sid:
            return self.error(
                response={
                    "message": "You need to Provided a ID of Question"
                },
                status=400
            )
        db = self.get_connection()
        try:
            async with await db.connection() as conn:  #pylint: disable=E1101
                ChatbotUsage.Meta.connection = conn
                # Getting a SID from sid
                question = await ChatbotUsage.get(sid=sid)
                if not question:
                    return self.error(
                        response={
                            "message": "Question not found"
                        },
                        status=404
                    )
                return self.json_response(
                    {
                        "chatbot": question.chatbot_id,
                        "question": question.question,
                        "answer": question.response,
                        "at": question.used_at
                    }
                )
        except Exception as e:
            return self.error(
                response={
                    "message": f"Error on Chatbot Sharing Question: {e}"
                },
                status=400
            )



class FeedbackTypeHandler(BaseView):
    """
    FeedbackTypeHandler.
    description: FeedbackTypeHandler for Parrot Application.
    """

    async def get(self):
        qs = self.get_arguments(self.request)
        category = qs.get('feedback_type', 'good').capitalize()
        feedback_list = FeedbackType.list_feedback(category)
        return self.json_response({
            "feedback": feedback_list
        })

# Manage Feedback:
class ChatbotFeedbackHandler(FormModel):
    """
    ChatbotFeedbackHandler.
    description: ChatbotFeedbackHandler for Parrot Application.
    """
    model = ChatbotFeedback
    path: str = '/api/v1/bot_feedback'

    def get_connection(self):
        params = {
            "credentials": BIGQUERY_CREDENTIALS,
            "project_id": BIGQUERY_PROJECT_ID,
        }
        return AsyncDB(
            'bigquery',
            params=params,
            force_closing=False
        )

    async def post(self):
        feedback = await self.validate_payload()
        if not feedback:
            return self.error(
                response={
                    "message": "Error on Bot Feedback"
                },
                status=400
            )
        db = self.get_connection()
        try:
            async with await db.connection() as conn:  # pylint: disable=E1101
                data = feedback.to_dict()
                # convert to string (bigquery uses json.dumps to convert to string)
                data['turn_id'] = str(data['turn_id'])
                data['chatbot_id'] = str(data['chatbot_id'])
                data['expiration_timestamp'] = str(data['expiration_timestamp'])
                if 'feedback_type' in data:
                    data['feedback_type'] = feedback.feedback_type.value
                else:
                    data['feedback_type'] = None
                
                # feedback data:
                data['session_id'] = str(data['session_id'])
                data['rating'] = data['rating']
                data['like'] = data['like']
                data['dislike'] = data['dislike']
                
                # writing directly to bigquery
                await conn.write(
                    [data],
                    table_id=ChatbotFeedback.Meta.name,
                    dataset_id=ChatbotFeedback.Meta.schema,
                    use_streams=False,
                    use_pandas=False
                )
                return self.json_response({
                    "message": "Bot Feedback Submitted, Thank you for your feedback!.",
                    "question": f"Question of ID: {feedback.turn_id} for bot {feedback.chatbot_id}"
                }, status=201)
        except Exception as e:
            return self.error(
                response={
                    "message": f"Error on Bot Feedback: {e}"
                },
                status=400
            )


class ChatbotHandler(AbstractModel):
    """Unified agent management handler.

    Manages agents from both PostgreSQL (BotModel) and
    AgentRegistry (YAML/BotConfig) with BotManager integration.

    Endpoints (configured via AbstractModel.configure):
        GET    /api/v1/bots            — list all agents (DB + registry)
        GET    /api/v1/bots/{id}       — single agent by name
        PUT    /api/v1/bots            — create new agent
        POST   /api/v1/bots/{id}       — update existing agent
        DELETE /api/v1/bots/{id}       — delete DB agent only
    """

    model = BotModel
    name: str = "Chatbot Management"
    pk: str = 'chatbot_id'

    # -- helpers ---------------------------------------------------------------

    @property
    def _manager(self):
        """Get BotManager from app context."""
        return self.request.app.get('bot_manager')

    @property
    def _registry(self):
        """Get AgentRegistry from BotManager."""
        manager = self._manager
        return manager.registry if manager else None

    def _agent_name_from_request(self) -> str | None:
        """Extract agent name from URL path or query string."""
        name = self.request.match_info.get('id')
        if not name:
            qs = self.query_parameters(self.request)
            name = qs.get('name')
        return name or None

    async def _get_db_agents(self) -> list[BotModel]:
        """Query all enabled agents from database."""
        db = self.handler
        try:
            async with await db(self.request) as conn:
                BotModel.Meta.connection = conn
                agents = await BotModel.filter(enabled=True)
                return agents if agents else []
        except Exception as exc:
            self.logger.error(f"Failed to load DB agents: {exc}")
            return []

    async def _get_db_agent(self, name: str) -> BotModel | None:
        """Query a single agent from database by name."""
        db = self.handler
        try:
            async with await db(self.request) as conn:
                BotModel.Meta.connection = conn
                try:
                    agent = await BotModel.get(name=name)
                    return agent
                except NoDataFound:
                    return None
        except Exception as exc:
            self.logger.error(f"Failed to load DB agent '{name}': {exc}")
            return None

    async def _check_duplicate(self, name: str) -> str | None:
        """Check if agent name exists in DB or registry.

        Returns the source ('database' or 'registry') if found, None otherwise.
        """
        # Check database
        db_agent = await self._get_db_agent(name)
        if db_agent:
            return 'database'
        # Check registry
        registry = self._registry
        if registry and registry.has(name):
            return 'registry'
        return None

    async def _register_bot_into_manager(
        self, bot_data: dict, app
    ) -> bool:
        """Create bot instance, configure it, and add to BotManager."""
        manager = self._manager
        if not manager:
            self.logger.error("No BotManager found on App")
            return False

        clsname = bot_data.pop('bot_class', 'BasicBot')
        botclass = manager.get_bot_class(clsname)
        name = bot_data.pop('name', 'NoName')

        try:
            bot = manager.create_bot(
                class_name=botclass,
                name=name,
                **bot_data
            )
        except Exception as exc:
            self.logger.error(
                f"Error creating bot instance of class {clsname}: {exc}"
            )
            return False

        if not bot:
            self.logger.error(
                f"Error creating bot instance of class {clsname}"
            )
            return False

        try:
            await bot.configure(app)
        except Exception as exc:
            self.logger.error(f"Error configuring bot {name}: {exc}")
            return False

        manager.add_bot(bot)
        self.logger.info(f"Bot '{name}' registered into BotManager")
        return True

    def _bot_model_to_dict(self, agent: BotModel) -> dict:
        """Serialize a BotModel instance for JSON response."""
        data = agent.to_dict()
        # Convert UUID to string for JSON serialization
        if 'chatbot_id' in data and data['chatbot_id'] is not None:
            data['chatbot_id'] = str(data['chatbot_id'])
        # Convert datetimes
        for key in ('created_at', 'updated_at'):
            if key in data and data[key] is not None:
                data[key] = str(data[key])
        data['source'] = 'database'
        return data

    def _registry_agent_to_dict(self, name: str, meta) -> dict:
        """Serialize a registry BotMetadata for JSON response."""
        if meta.bot_config is not None:
            try:
                data = meta.bot_config.model_dump(mode="json")
            except Exception:
                data = {"name": meta.name}
        else:
            data = {
                "name": meta.name,
                "module_path": meta.module_path,
                "file_path": str(meta.file_path),
                "singleton": meta.singleton,
                "at_startup": meta.at_startup,
                "priority": meta.priority,
                "tags": sorted(meta.tags) if meta.tags else [],
            }
        data['source'] = 'registry'
        return data

    # -- HTTP Methods ----------------------------------------------------------

    async def get(self):
        """Return agents from database and AgentRegistry.

        GET /api/v1/bots          — list all agents
        GET /api/v1/bots/{id}     — single agent by name
        """
        await self.session()
        agent_name = self._agent_name_from_request()

        if agent_name:
            return await self._get_one(agent_name)
        return await self._get_all()

    async def _get_one(self, name: str):
        """Return a single agent by name, checking DB first."""
        # 1. Check database
        db_agent = await self._get_db_agent(name)
        if db_agent:
            return self.json_response(self._bot_model_to_dict(db_agent))

        # 2. Check registry
        registry = self._registry
        if registry:
            meta = registry._registered_agents.get(name)
            if meta:
                return self.json_response(
                    self._registry_agent_to_dict(name, meta)
                )

        return self.error(
            response={"message": f"Agent '{name}' not found"},
            status=404
        )

    async def _get_all(self):
        """Return merged list of all agents from DB and registry."""
        agents = []
        seen_names: set[str] = set()

        # 1. Database agents (higher priority)
        db_agents = await self._get_db_agents()
        for agent in db_agents:
            data = self._bot_model_to_dict(agent)
            agents.append(data)
            seen_names.add(agent.name)

        # 2. Registry agents (skip duplicates already in DB)
        registry = self._registry
        if registry:
            for name, meta in registry._registered_agents.items():
                if name in seen_names:
                    continue
                agents.append(self._registry_agent_to_dict(name, meta))

        return self.json_response({
            "agents": agents,
            "total": len(agents),
        })

    async def put(self):
        """Create a new agent.

        Payload must include 'storage' field: 'database' or 'registry'.
        For database: inserts BotModel, configures, registers into BotManager.
        For registry: creates BotConfig YAML, registers into AgentRegistry + BotManager.
        """
        await self.session()

        try:
            payload = await self.json_data()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400
            )

        if not payload:
            return self.error(
                response={"message": "Request body is required"},
                status=400
            )

        storage = payload.pop('storage', 'database')
        name = payload.get('name')

        if not name:
            return self.error(
                response={"message": "'name' is required"},
                status=400
            )

        # Check for duplicates across both sources
        existing = await self._check_duplicate(name)
        if existing:
            return self.error(
                response={
                    "message": (
                        f"Agent '{name}' already exists in {existing}. "
                        "Use POST to update."
                    )
                },
                status=409
            )

        if storage == 'database':
            return await self._put_database(payload)
        elif storage == 'registry':
            return await self._put_registry(payload)
        else:
            return self.error(
                response={
                    "message": (
                        f"Invalid storage '{storage}'. "
                        "Must be 'database' or 'registry'."
                    )
                },
                status=400
            )

    async def _put_database(self, payload: dict):
        """Create agent in database and register into BotManager."""
        # Set created_by from session
        try:
            payload['created_by'] = await self.get_userid(
                session=self._session
            )
        except Exception:
            pass

        db = self.handler
        try:
            async with await db(self.request) as conn:
                BotModel.Meta.connection = conn
                bot_model = BotModel(**payload)
                await bot_model.insert()

                # Register into BotManager
                bot_data = bot_model.to_bot_config()
                bot_data['name'] = bot_model.name
                bot_data['bot_class'] = payload.get('bot_class', 'BasicBot')
                await self._register_bot_into_manager(
                    bot_data, self.request.app
                )

                return self.json_response(
                    {
                        "message": f"Agent '{bot_model.name}' created in database",
                        "chatbot_id": str(bot_model.chatbot_id),
                        "name": bot_model.name,
                        "source": "database",
                    },
                    status=201
                )
        except Exception as exc:
            return self.error(
                response={"message": f"Failed to create agent: {exc}"},
                status=400
            )

    async def _put_registry(self, payload: dict):
        """Create agent in AgentRegistry (YAML) and register into BotManager."""
        registry = self._registry
        if not registry:
            return self.error(
                response={"message": "AgentRegistry not available"},
                status=500
            )

        try:
            config = BotConfig(**payload)
        except Exception as exc:
            return self.error(
                response={"message": f"Invalid BotConfig: {exc}"},
                status=400
            )

        category = payload.pop('category', 'general')

        # Write YAML definition
        try:
            file_path = registry.create_agent_definition(
                config, category=category
            )
        except Exception as exc:
            return self.error(
                response={"message": f"Failed to write YAML: {exc}"},
                status=500
            )

        # Register into AgentRegistry runtime
        try:
            factory = registry.create_agent_factory(config)
            from ..registry.registry import BotMetadata
            registry._registered_agents[config.name] = BotMetadata(
                name=config.name,
                factory=factory,
                module_path=config.module,
                file_path=file_path,
                singleton=config.singleton,
                at_startup=config.at_startup,
                startup_config=config.config,
                tags=config.tags or set(),
                priority=config.priority,
            )
        except Exception as exc:
            self.logger.warning(
                f"YAML written but runtime registration failed: {exc}"
            )

        # Register into BotManager
        manager = self._manager
        if manager:
            try:
                bot_instance = await registry.get_instance(config.name)
                if bot_instance:
                    if not getattr(bot_instance, 'is_configured', False):
                        await bot_instance.configure(self.request.app)
                    manager.add_bot(bot_instance)
            except Exception as exc:
                self.logger.warning(
                    f"Registry agent created but BotManager registration "
                    f"failed: {exc}"
                )

        return self.json_response(
            {
                "message": f"Agent '{config.name}' created in registry",
                "name": config.name,
                "file_path": str(file_path),
                "source": "registry",
            },
            status=201
        )

    async def post(self):
        """Update an existing agent.

        Looks up by name — DB has priority. Updates in-place and
        re-configures the live bot in BotManager.
        """
        await self.session()

        agent_name = self._agent_name_from_request()
        if not agent_name:
            return self.error(
                response={"message": "Agent name is required in URL"},
                status=400
            )

        try:
            payload = await self.json_data()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400
            )

        if not payload:
            return self.error(
                response={"message": "Request body is required"},
                status=400
            )

        # Check database first (DB has priority)
        db_agent = await self._get_db_agent(agent_name)
        if db_agent:
            return await self._post_database(db_agent, payload)

        # Check registry
        registry = self._registry
        if registry and registry.has(agent_name):
            return await self._post_registry(agent_name, payload)

        return self.error(
            response={"message": f"Agent '{agent_name}' not found"},
            status=404
        )

    async def _post_database(self, agent: BotModel, payload: dict):
        """Update a database-backed agent."""
        db = self.handler
        try:
            async with await db(self.request) as conn:
                BotModel.Meta.connection = conn
                for key, val in payload.items():
                    if key in ('chatbot_id', 'created_at', 'created_by'):
                        continue  # immutable fields
                    agent.set(key, val)
                agent.set('updated_at', datetime.now())
                await agent.update()

                # Re-register into BotManager with updated config
                manager = self._manager
                if manager:
                    # Remove old instance if present
                    try:
                        manager.remove_bot(agent.name)
                    except (KeyError, Exception):
                        pass
                    bot_data = agent.to_bot_config()
                    bot_data['name'] = agent.name
                    bot_data['bot_class'] = getattr(
                        agent, 'bot_class', 'BasicBot'
                    ) or 'BasicBot'
                    await self._register_bot_into_manager(
                        bot_data, self.request.app
                    )

                return self.json_response({
                    "message": f"Agent '{agent.name}' updated in database",
                    "name": agent.name,
                    "source": "database",
                })
        except Exception as exc:
            return self.error(
                response={"message": f"Failed to update agent: {exc}"},
                status=400
            )

    async def _post_registry(self, name: str, payload: dict):
        """Update a registry-backed agent via YAML overwrite."""
        registry = self._registry
        meta = registry._registered_agents.get(name)

        # Build updated config from existing + payload
        if meta and meta.bot_config:
            existing = meta.bot_config.model_dump(mode="json")
            existing.update(payload)
            existing['name'] = name  # name is immutable
        else:
            existing = payload
            existing['name'] = name

        try:
            config = BotConfig(**existing)
        except Exception as exc:
            return self.error(
                response={"message": f"Invalid BotConfig: {exc}"},
                status=400
            )

        category = payload.pop('category', 'general')

        # Overwrite YAML definition
        try:
            file_path = registry.create_agent_definition(
                config, category=category
            )
        except Exception as exc:
            return self.error(
                response={"message": f"Failed to update YAML: {exc}"},
                status=500
            )

        # Update runtime registry
        try:
            factory = registry.create_agent_factory(config)
            from ..registry.registry import BotMetadata
            registry._registered_agents[name] = BotMetadata(
                name=config.name,
                factory=factory,
                module_path=config.module,
                file_path=file_path,
                singleton=config.singleton,
                at_startup=config.at_startup,
                startup_config=config.config,
                tags=config.tags or set(),
                priority=config.priority,
            )
        except Exception as exc:
            self.logger.warning(
                f"YAML updated but runtime re-registration failed: {exc}"
            )

        # Re-register into BotManager
        manager = self._manager
        if manager:
            try:
                manager.remove_bot(name)
            except (KeyError, Exception):
                pass
            try:
                bot_instance = await registry.get_instance(name)
                if bot_instance:
                    if not getattr(bot_instance, 'is_configured', False):
                        await bot_instance.configure(self.request.app)
                    manager.add_bot(bot_instance)
            except Exception as exc:
                self.logger.warning(
                    f"Registry agent updated but BotManager re-registration "
                    f"failed: {exc}"
                )

        return self.json_response({
            "message": f"Agent '{name}' updated in registry",
            "name": name,
            "file_path": str(file_path),
            "source": "registry",
        })

    async def delete(self):
        """Delete a database-backed agent.

        Registry/YAML-based agents cannot be deleted via this endpoint.
        """
        await self.session()

        agent_name = self._agent_name_from_request()
        if not agent_name:
            return self.error(
                response={"message": "Agent name is required"},
                status=400
            )

        # Refuse to delete registry-based agents
        registry = self._registry
        if registry and registry.has(agent_name):
            db_agent = await self._get_db_agent(agent_name)
            if not db_agent:
                return self.error(
                    response={
                        "message": (
                            f"Agent '{agent_name}' is registry-based (YAML/code) "
                            "and cannot be deleted via this endpoint."
                        )
                    },
                    status=403
                )

        # Delete from database
        db_agent = await self._get_db_agent(agent_name)
        if not db_agent:
            return self.error(
                response={"message": f"Agent '{agent_name}' not found in database"},
                status=404
            )

        db = self.handler
        try:
            async with await db(self.request) as conn:
                BotModel.Meta.connection = conn
                await db_agent.delete()

                # Remove from BotManager
                manager = self._manager
                if manager:
                    try:
                        manager.remove_bot(agent_name)
                    except (KeyError, Exception):
                        pass

                return self.json_response({
                    "message": f"Agent '{agent_name}' deleted",
                    "name": agent_name,
                })
        except Exception as exc:
            return self.error(
                response={"message": f"Failed to delete agent: {exc}"},
                status=400
            )

@user_session()
class ToolList(BaseView):
    """
    ToolList.
    description: ToolList for Parrot Application.
    """
    async def get(self):
        registry = ToolRegistry()
        try:
            tools = registry.discover_tools()
            return self.json_response({
                "tools": tools
            })
        except Exception as e:
            return self.error(
                response={
                    "message": f"Error on Tool List: {e}"
                },
                status=400
            )
