from __future__ import annotations
import re
import uuid as _uuid
from datetime import datetime
from asyncdb import AsyncDB  # asyncdb[default] is in core deps
from asyncdb.exceptions import NoDataFound
# PBAC (Policy-Based Access Control) — optional, fail-open if absent
from navigator_auth.decorators import user_session
try:
    from navigator_auth.abac.policies.resources import ResourceType as _ResourceType
    from navigator_auth.abac.context import EvalContext as _EvalContext
    from navigator_auth.conf import AUTH_SESSION_OBJECT as _AUTH_SESSION
    _PBAC_AVAILABLE = True
except ImportError:
    _ResourceType = _EvalContext = _AUTH_SESSION = None
    _PBAC_AVAILABLE = False

from navigator.views import (
    ModelView,
    BaseView,
    FormModel
)
from navigator.views.abstract import AbstractModel
from parrot.conf import (
    BIGQUERY_CREDENTIALS,
    BIGQUERY_PROJECT_ID,
)
from parrot.utils.naming import slugify_name, deduplicate_name
from .models import (
    BotModel,
    ChatbotUsage,
    PromptLibrary,
    UserPrompts,
    ChatbotFeedback,
    FeedbackType
)
from ..tools.discovery import discover_all
from ..registry.registry import BotConfig
# FEAT-133: reranker + parent-searcher factories (used in _register_bot_into_manager)
from ..exceptions import ConfigError
from ..rerankers.factory import create_reranker
from ..stores.parents.factory import create_parent_searcher


class _PBACHandlerMixin:
    """Mixin that provides PBAC helper methods for aiohttp handlers.

    Both ``ChatbotHandler`` and ``ToolList`` need the same eval-context
    construction and evaluator lookup. Rather than duplicate these methods,
    both classes inherit this mixin.

    Requires the host class to expose ``self.request`` (standard for all
    navigator ``BaseView`` / ``AbstractModel`` subclasses).
    """

    def _get_pbac_evaluator(self):
        """Return the PDP evaluator from ``app['abac']``, or ``None``.

        Returns:
            ``PolicyEvaluator`` instance when PBAC is configured,
            ``None`` otherwise (fail-open).
        """
        if not _PBAC_AVAILABLE:
            return None
        pdp = self.request.app.get('abac')
        return getattr(pdp, '_evaluator', None) if pdp is not None else None

    async def _build_eval_context(self):
        """Build an ``EvalContext`` from the current request session.

        Follows the pattern from ``agent.py:_build_eval_context()``.
        Returns ``None`` if PBAC is not available or the session cannot
        be read (fail-open callers must handle ``None``).

        Returns:
            ``EvalContext`` instance, or ``None`` if unavailable.
        """
        if not _PBAC_AVAILABLE:
            return None
        try:
            session = getattr(self.request, 'session', None)
            if session is None:
                try:
                    from navigator_session import get_session  # noqa: PLC0415
                    session = await get_session(self.request)
                except Exception:  # pylint: disable=broad-except
                    return None
            userinfo = session.get(_AUTH_SESSION, {}) if session else {}
            return _EvalContext(
                username=userinfo.get('username', ''),
                groups=set(userinfo.get('groups', [])),
                roles=set(userinfo.get('roles', [])),
                programs=userinfo.get('programs', []),
            )
        except Exception:  # pylint: disable=broad-except
            return None


_AGENT_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


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

    async def get(self):
        """Override GET to filter by chatbot_id OR agent_id query param.

        Returns HTTP 400 if both are supplied simultaneously.
        Validates chatbot_id as a UUID and agent_id as a registry slug.
        Falls through to the inherited ModelView behaviour when neither
        is present.
        """
        q = self.request.rel_url.query
        chatbot_id = q.get("chatbot_id")
        agent_id = q.get("agent_id")

        if chatbot_id and agent_id:
            return self.error(
                response={
                    "message": (
                        "Provide exactly one of chatbot_id or agent_id, not both."
                    ),
                },
                status=400,
            )

        if chatbot_id:
            try:
                _uuid.UUID(chatbot_id)
            except (ValueError, TypeError):
                return self.error(
                    response={"message": "chatbot_id must be a valid UUID."},
                    status=400,
                )
            return await super().get()

        if agent_id:
            if not _AGENT_SLUG_RE.match(agent_id):
                return self.error(
                    response={
                        "message": (
                            "agent_id must match [a-z0-9_-]+ "
                            "(registry slug format)."
                        ),
                    },
                    status=400,
                )
            return await super().get()

        return await super().get()


class UserPromptsManagement(ModelView):
    """Per-user prompt library.

    Exposes CRUD over ``navigator.users_prompts`` at
    ``/api/v1/agents/user_prompts``. Every read/write is scoped to the
    authenticated ``user_id``; clients cannot supply or spoof it.
    """

    model = UserPrompts
    name: str = "User Prompts Management"
    path: str = '/api/v1/agents/user_prompts'
    pk: str = 'prompt_id'

    async def _set_user_id(self, value, column, data):
        # ALWAYS overwrite — the request must not carry a client-supplied user_id.
        return await self.get_userid(session=self._session)

    async def _set_created_by(self, value, column, data):
        if not value:
            return await self.get_userid(session=self._session)
        return value

    async def get(self):
        """Override GET to require an authenticated session.

        self._session is only populated by service_auth, which wraps the
        parent get() — so it must be loaded explicitly before reading the
        user here, otherwise get_userid(None) rejects every request with
        a 403. Row filtering comes from the query-string params handled
        by ModelView's generic machinery (user_id, chatbot_id).
        """
        await self.session()
        await self.get_userid(session=self._session)
        return await super().get()


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
            async with await db.connection() as conn:  # pylint: disable=E1101
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
            async with await db.connection() as conn:  # pylint: disable=E1101
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


class ChatbotHandler(_PBACHandlerMixin, AbstractModel):
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
            self.logger.error("Failed to load DB agents: %s", exc)
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
            self.logger.error("Failed to load DB agent '%s': %s", name, exc)
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
    ):
        """Create bot instance, configure it, and add to BotManager.

        Applies the FEAT-133 factory sequence so that ``reranker_config`` and
        ``parent_searcher_config`` are resolved into live objects on the bot
        instance, both during creation (PUT) and updates (POST).

        Returns:
            The configured bot instance, or None on failure.
        """
        manager = self._manager
        if not manager:
            self.logger.error("No BotManager found on App")
            return None

        clsname = bot_data.pop('bot_class', 'BasicBot')
        botclass = manager.get_bot_class(clsname)
        name = bot_data.pop('name', 'NoName')

        # FEAT-133 Step 1: Build reranker BEFORE bot construction.
        # Extract the configs before passing **bot_data to create_bot so the
        # constructor does not receive unknown kwargs.
        reranker_config = bot_data.pop('reranker_config', {}) or {}
        parent_searcher_config = bot_data.pop('parent_searcher_config', {}) or {}

        expand_to_parent = bool(parent_searcher_config.get("expand_to_parent", False))

        try:
            reranker = create_reranker(reranker_config, bot_llm_client=None)
        except ConfigError as exc:
            self.logger.error(
                "Bot '%s': invalid reranker_config: %s", name, exc
            )
            return None

        try:
            bot = manager.create_bot(
                class_name=botclass,
                name=name,
                reranker=reranker,
                expand_to_parent=expand_to_parent,
                **bot_data
            )
        except Exception as exc:
            self.logger.error(
                f"Error creating bot instance of class {clsname}: {exc}"
            )
            return None

        if not bot:
            self.logger.error(
                f"Error creating bot instance of class {clsname}"
            )
            return None

        try:
            await bot.configure(app)
        except Exception as exc:
            self.logger.error("Error configuring bot %s: %s", name, exc)
            return None

        # FEAT-133 Step 2: Patch LLM reranker client post-configure.
        from ..rerankers.llm import LLMReranker  # noqa: PLC0415
        if isinstance(reranker, LLMReranker) and reranker.client is None:
            reranker.client = getattr(bot, 'llm_client', None)

        # FEAT-133 Step 3: Build parent_searcher AFTER configure() (needs bot.store).
        try:
            parent_searcher = create_parent_searcher(
                parent_searcher_config,
                store=getattr(bot, 'store', None),
            )
        except ConfigError as exc:
            self.logger.error(
                "Bot '%s': invalid parent_searcher_config: %s", name, exc
            )
            return None

        if parent_searcher is not None:
            bot.parent_searcher = parent_searcher

        manager.add_bot(bot)
        self.logger.info(
            "Bot '%s' registered into BotManager (reranker=%s, parent_searcher=%s)",
            name,
            type(reranker).__name__ if reranker else None,
            type(parent_searcher).__name__ if parent_searcher else None,
        )

        # PBAC: register class-declared policy_rules for dynamically created bots.
        # Bots created at runtime via PUT /api/v1/bots bypass AgentRegistry.register(),
        # so their policies must be explicitly registered here.
        registry = getattr(manager, 'registry', None)
        if registry is not None and hasattr(registry, '_collect_and_register_policies'):
            registry._collect_and_register_policies(name, type(bot), None)  # noqa: SLF001

        return bot

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
        """Return a single agent by name, checking DB first.

        Applies PBAC ``agent:list`` check when PDP is configured. Returns
        403 if denied. Fails open when PDP is not configured.
        """
        # PBAC: check agent:list access for this specific agent
        evaluator = self._get_pbac_evaluator()
        if evaluator is not None:
            ctx = await self._build_eval_context()
            if ctx is not None:
                try:
                    result = evaluator.check_access(
                        ctx, _ResourceType.AGENT, name, "agent:list"
                    )
                    if not result.allowed:
                        self.logger.info(
                            "PBAC: agent:list denied for user=%s agent=%s",
                            ctx.username if hasattr(ctx, 'username') else 'unknown', name,
                        )
                        return self.error(
                            response={"message": "Access denied"},
                            status=403,
                        )
                except Exception as exc:  # pylint: disable=broad-except
                    self.logger.warning(
                        "PBAC: evaluator error for agent=%s, failing open: %s",
                        name, exc,
                    )

        # 1. Check database
        db_agent = await self._get_db_agent(name)
        if db_agent:
            return self.json_response(self._bot_model_to_dict(db_agent))

        # 2. Check registry
        registry = self._registry
        if registry:
            meta = registry.get_metadata(name)
            if meta:
                return self.json_response(
                    self._registry_agent_to_dict(name, meta)
                )

        return self.error(
            response={"message": f"Agent '{name}' not found"},
            status=404
        )

    async def _get_all(self):
        """Return merged list of all agents from DB and registry.

        Applies PBAC batch filtering via ``evaluator.filter_resources()``
        when PDP is configured. Fails open (returns all) when PDP absent.
        """
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
            for meta in registry.list_bots_by_priority():
                if meta.name in seen_names:
                    continue
                agents.append(self._registry_agent_to_dict(meta.name, meta))

        # 3. PBAC batch filtering
        evaluator = self._get_pbac_evaluator()
        if evaluator is not None and agents:
            ctx = await self._build_eval_context()
            if ctx is not None:
                try:
                    agent_names = [a["name"] for a in agents]
                    result = evaluator.filter_resources(
                        ctx, _ResourceType.AGENT, agent_names, "agent:list"
                    )
                    # Use a sentinel to distinguish "attribute absent" (→ fail-open)
                    # from "empty list" (→ deny all).  The `or` short-circuit must
                    # NOT be used here: result.allowed=[] means deny-all, not fail-open.
                    _sentinel = object()
                    _raw = getattr(result, 'allowed', _sentinel)
                    if _raw is _sentinel:
                        allowed_names: set[str] = set(agent_names)  # unknown shape → fail-open
                    else:
                        allowed_names = set(_raw) if _raw is not None else set()
                    agents = [a for a in agents if a["name"] in allowed_names]
                except Exception as exc:  # pylint: disable=broad-except
                    self.logger.warning(
                        "PBAC: filter_resources error, failing open: %s", exc
                    )

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

        if storage == 'database':
            # Slugify and deduplicate name for database agents
            original_name = name.strip()
            try:
                slug = slugify_name(original_name)
            except ValueError:
                return self.error(
                    response={
                        "message": (
                            f"Name '{original_name}' produces an empty slug "
                            "after normalization. Provide a name with "
                            "alphanumeric characters."
                        )
                    },
                    status=400
                )
            try:
                final_name = await deduplicate_name(
                    slug, self._check_duplicate
                )
            except ValueError:
                return self.error(
                    response={
                        "message": (
                            f"All name variants for '{slug}' are taken. "
                            "Choose a different name."
                        )
                    },
                    status=409
                )
            payload['name'] = final_name
            # Preserve original name in description if it changed
            if original_name != final_name:
                desc = payload.get('description', '') or ''
                payload['description'] = (
                    f"Display name: {original_name}. {desc}".strip()
                )
            return await self._put_database(payload)

        elif storage == 'registry':
            # Registry path: simple duplicate check, no slugification
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
        # FEAT-133: Shallow validation for new JSONB config fields.
        for _key in ("reranker_config", "parent_searcher_config"):
            if _key in payload and not isinstance(payload[_key], dict):
                return self.error(
                    response={"message": f"{_key} must be a JSON object"},
                    status=400,
                )

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
                bot_instance = await self._register_bot_into_manager(
                    bot_data, self.request.app
                )

                # Provision vector store if configured. The embedding
                # model is carried inside vector_store_config itself.
                vs_config = payload.get('vector_store_config') or {}
                vs_result = await self._provision_vector_store(
                    bot_instance,
                    vs_config,
                )

                response_data = {
                    "message": f"Agent '{bot_model.name}' created in database",
                    "chatbot_id": str(bot_model.chatbot_id),
                    "name": bot_model.name,
                    "source": "database",
                    "vector_store_status": vs_result["status"],
                }
                if vs_result.get("error"):
                    response_data["vector_store_error"] = vs_result["error"]

                return self.json_response(response_data, status=201)
        except Exception as exc:
            return self.error(
                response={"message": f"Failed to create agent: {exc}"},
                status=400
            )

    async def _provision_vector_store(
        self,
        bot,
        vector_store_config: dict,
    ) -> dict:
        """Eagerly create the PgVector table for a bot's vector store.

        Args:
            bot: The configured bot instance (may be None if registration failed).
            vector_store_config: The user-provided vector store configuration
                dict. The embedding model lives at
                ``vector_store_config['embedding_model']`` (single source of
                truth).

        Returns:
            Dict with ``"status"`` (``"none"``, ``"ready"``, or ``"pending"``)
            and optionally ``"error"`` when status is ``"pending"``.
        """
        if not bot or not vector_store_config:
            return {"status": "none"}

        table = vector_store_config.get('table')
        schema = vector_store_config.get('schema')
        if not table or not schema:
            return {"status": "none"}

        store_type = vector_store_config.get('name', 'postgres')
        dimension = vector_store_config.get('dimension', 384)
        embedding_model = vector_store_config.get('embedding_model')

        # FEAT-150: validate Matryoshka config at provision time so mismatches
        # are caught with a clear ConfigError before the pgvector table is
        # created.  Without this, a dim disagreement would surface as a
        # cryptic pgvector error at insert time.
        if embedding_model:
            matryoshka_dict = embedding_model.get("matryoshka")
            if isinstance(matryoshka_dict, dict) and matryoshka_dict.get("enabled"):
                from parrot.embeddings.matryoshka import (
                    MatryoshkaConfig,
                    validate_against_catalog,
                )
                from parrot.exceptions import ConfigError
                try:
                    cfg = MatryoshkaConfig(**matryoshka_dict)
                except Exception as exc:
                    raise ConfigError(
                        f"Invalid matryoshka config in "
                        f"vector_store_config.embedding_model: {exc}"
                    ) from exc
                # Validate against the catalog (model in catalog + dim allowed).
                validate_against_catalog(cfg, embedding_model.get("model_name", ""))
                # Enforce dimension equality between the pgvector column width
                # (vector_store_config.dimension) and the Matryoshka truncation dim.
                if cfg.dimension != dimension:
                    raise ConfigError(
                        f"vector_store_config.dimension ({dimension}) must equal "
                        f"embedding_model.matryoshka.dimension ({cfg.dimension}) "
                        f"because the pgvector column is created with the former. "
                        f"Update both values to match."
                    )

        store_kwargs = {
            'table': table,
            'schema': schema,
            'dimension': dimension,
        }
        if embedding_model:
            store_kwargs['embedding_model'] = embedding_model

        try:
            bot.define_store(vector_store=store_type, **store_kwargs)
            bot.configure_store()
            await bot.store.connection()
            await bot.store.create_collection(
                table=table, schema=schema, dimension=dimension
            )
            self.logger.info(
                f"Vector store table '{schema}.{table}' created for bot '{bot.name}'"
            )
            return {"status": "ready"}
        except Exception as exc:
            self.logger.error(
                f"Vector store provisioning failed for '{bot.name}': {exc}"
            )
            return {"status": "pending", "error": str(exc)}

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
            # TODO: replace with registry.register() once signature confirmed
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
        # FEAT-133: Shallow validation for new JSONB config fields.
        for _key in ("reranker_config", "parent_searcher_config"):
            if _key in payload and not isinstance(payload[_key], dict):
                return self.error(
                    response={"message": f"{_key} must be a JSON object"},
                    status=400,
                )

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
        meta = registry.get_metadata(name)

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
            # TODO: replace with registry.register() once signature confirmed
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

        # Registry-based agents: only factory-created ones can be deleted.
        # Repo-committed YAMLs are protected (the file would just be re-loaded
        # at next startup, so deletion via API is a no-op at best).
        registry = self._registry
        if registry and registry.has(agent_name):
            db_agent = await self._get_db_agent(agent_name)
            if not db_agent:
                metadata = registry.get_metadata(agent_name)
                bot_config = getattr(metadata, "bot_config", None)
                origin = getattr(bot_config, "origin", "repo") if bot_config else "repo"
                if origin == "factory":
                    ok, reason = registry.delete_factory_agent(agent_name)
                    if not ok:
                        return self.error(
                            response={"message": reason},
                            status=500,
                        )
                    manager = self._manager
                    if manager:
                        try:
                            manager.remove_bot(agent_name)
                        except (KeyError, Exception):
                            pass
                    return self.json_response({
                        "message": f"Factory agent '{agent_name}' deleted",
                        "name": agent_name,
                        "source": "factory",
                    })
                return self.error(
                    response={
                        "message": (
                            f"Agent '{agent_name}' is a repo YAML/code agent "
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
class ToolList(_PBACHandlerMixin, BaseView):
    """ToolList — returns all registered tools, PBAC-filtered when PDP configured.

    When the PDP evaluator is available (``app['abac']`` is set), tools are
    filtered using ``evaluator.filter_resources(..., ResourceType.TOOL, ...,
    "tool:list")``. Returns all tools when PDP is absent (fail-open).

    PBAC helpers (``_get_pbac_evaluator``, ``_build_eval_context``) are
    inherited from ``_PBACHandlerMixin``.
    """

    async def get(self):
        """List all tools, filtered by PBAC ``tool:list`` action when PDP configured."""
        try:
            raw = discover_all()
            tools = {}
            for name, value in raw.items():
                if isinstance(value, str):
                    tools[name] = {
                        "tool_name": name,
                        "module_path": value,
                    }
                else:
                    tools[name] = {
                        "tool_name": getattr(value, "name", name),
                        "module_path": f"{value.__module__}.{value.__qualname__}",
                        "description": getattr(
                            value, "description",
                            value.__doc__ or ""
                        ),
                    }

            # PBAC: filter tools by tool:list permission
            evaluator = self._get_pbac_evaluator()
            if evaluator is not None and tools:
                ctx = await self._build_eval_context()
                if ctx is not None:
                    try:
                        tool_names = list(tools.keys())
                        result = evaluator.filter_resources(
                            ctx, _ResourceType.TOOL, tool_names, "tool:list"
                        )
                        # Sentinel distinguishes "attribute absent" (fail-open) from
                        # "empty list" (deny all).  Do NOT use `or tool_names` here.
                        _sentinel = object()
                        _raw = getattr(result, 'allowed', _sentinel)
                        if _raw is _sentinel:
                            allowed_names: set[str] = set(tool_names)  # unknown shape → fail-open
                        else:
                            allowed_names = set(_raw) if _raw is not None else set()
                        tools = {k: v for k, v in tools.items() if k in allowed_names}
                    except Exception as exc:  # pylint: disable=broad-except
                        self.logger.warning(
                            "PBAC: ToolList filter error, failing open: %s", exc
                        )

            return self.json_response({"tools": tools})
        except Exception as e:
            return self.error(
                response={
                    "message": f"Error on Tool List: {e}"
                },
                status=400
            )
