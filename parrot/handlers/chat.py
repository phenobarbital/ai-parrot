from typing import Union
from collections import defaultdict
import re
import uuid
import asyncio
import importlib
import inspect
from pathlib import Path
from aiohttp import web
from asyncdb.exceptions.exceptions import NoDataFound  # pylint: disable=E0611  # noqa
from datamodel.exceptions import ValidationError  # pylint: disable=E0611  # noqa
from datamodel.parsers.json import json_encoder  # noqa  pylint: disable=E0611
from navigator_auth.decorators import (
    is_authenticated,
    user_session,
    allowed_organizations
)
from navigator.views import BaseView
from ..bots.abstract import AbstractBot
from ..loaders import AbstractLoader, AVAILABLE_LOADERS
from ..loaders.markdown import MarkdownLoader
from .models import BotModel
from ..models.responses import AIMessage
from ..outputs import OutputFormatter, OutputMode



@is_authenticated()
@user_session()
class ChatHandler(BaseView):
    """
    ChatHandler.
    description: Chat Handler for Parrot Application.
    """

    async def get(self, **kwargs):
        """
        Obtener información de un chatbot
        ---
        tags:
        - chatbots
        summary: Info de un chatbot o bienvenida al servicio
        description: |
        Si no se especifica nombre de chatbot, retorna mensaje de bienvenida.
        Si se especifica nombre, retorna configuración y detalles del chatbot.
        operationId: getChatbotInfo
        parameters:
        - $ref: "#/components/parameters/ChatbotName"
        responses:
        "200":
            description: Información del chatbot o mensaje de bienvenida
            content:
            application/json:
                schema:
                oneOf:
                    - type: object
                    properties:
                        message:
                        type: string
                        example: "Welcome to Parrot Chatbot Service."
                    - $ref: "#/components/schemas/ChatbotInfo"
                examples:
                welcome:
                    summary: Sin chatbot especificado
                    value:
                    message: "Welcome to Parrot Chatbot Service."
                chatbot_info:
                    summary: Con chatbot especificado
                    value:
                    chatbot: "nextstop"
                    description: "Travel planning assistant"
                    role: "You are a helpful travel agent"
                    embedding_model: "text-embedding-3-small"
                    llm: "ChatOpenAI(model='gpt-4', temperature=0.7)"
                    temperature: 0.7
                    config_file: "/config/bots/nextstop.yaml"
        "404":
            $ref: "#/components/responses/NotFound"
        "401":
            $ref: "#/components/responses/Unauthorized"
        security:
        - sessionAuth: []
        """
        if (name := self.request.match_info.get('chatbot_name', None)):
            # retrieve chatbof information:
            manager = self.request.app['bot_manager']
            chatbot = await manager.get_bot(name)
            if not chatbot:
                return self.error(
                    f"Chatbot {name} not found.",
                    status=404
                )
            config_file = getattr(chatbot, 'config_file', None)
            return self.json_response({
                "chatbot": chatbot.name,
                "description": chatbot.description,
                "role": chatbot.role,
                "embedding_model": chatbot.embedding_model,
                "llm": f"{chatbot.llm!r}",
                "temperature": chatbot.llm.temperature,
                "config_file": config_file
            })
        else:
            return self.json_response({
                "message": "Welcome to Parrot Chatbot Service."
            })

    def _check_methods(self, bot: AbstractBot, method_name: str):
        """Check if the method exists in the bot and is callable."""
        forbidden_methods = {
            '__init__', '__del__', '__getattribute__', '__setattr__',
            'configure', '_setup_database_tools', 'save', 'delete',
            'update', 'insert', '__dict__', '__class__', 'retrieval',
            '_define_prompt', 'configure_llm', 'configure_store', 'default_tools'
        }
        if not method_name:
            return None
        if method_name.startswith('_') or method_name in forbidden_methods:
            raise AttributeError(
                f"Method {method_name} error, not found or forbidden."
            )
        if not hasattr(bot, method_name):
            raise AttributeError(
                f"Method {method_name} error, not found or forbidden."
            )
        method = getattr(bot, method_name)
        if not callable(method):
            raise TypeError(
                f"Attribute {method_name} is not callable in bot {bot.name}."
            )
        return method

    async def post(self, *args, **kwargs):
        """
        Interactuar con un chatbot
        ---
        tags:
        - chatbots
        summary: Enviar mensaje a un chatbot
        description: |
        Endpoint principal para interactuar con chatbots. Soporta:

        - Conversaciones con contexto (RAG)
        - Búsqueda en vector store (similarity, MMR, ensemble)
        - Override de LLM y modelo
        - Upload de archivos (multipart/form-data)
        - Invocación de métodos personalizados del bot

        ## Modos de uso

        ### 1. Chat básico
        ```json
        {
            "query": "¿Cuál es la capital de Francia?"
        }
        ```

        ### 2. Chat con configuración personalizada
        ```json
        {
            "query": "Explica el concepto de RAG",
            "llm": "openai",
            "model": "gpt-4-turbo",
            "temperature": 0.3,
            "search_type": "mmr",
            "return_sources": true
        }
        ```

        ### 3. Invocar método personalizado
        ```
        POST /api/v1/chat/{chatbot_name}/summarize
        {
            "text": "Long text to summarize...",
            "max_length": 100
        }
        ```

        ### 4. Upload de archivos
        ```
        Content-Type: multipart/form-data

        query: "Analiza este documento"
        file: [documento.pdf]
        ```

        operationId: chatWithBot
        parameters:
        - $ref: "#/components/parameters/ChatbotName"
        - $ref: "#/components/parameters/MethodName"
        requestBody:
        required: true
        description: Mensaje y configuración de la conversación
        content:
            application/json:
            schema:
                $ref: "#/components/schemas/ChatRequest"
            examples:
                basic_chat:
                summary: Chat básico
                value:
                    query: "¿Cuál es el mejor momento para visitar Japón?"

                advanced_chat:
                summary: Chat con opciones avanzadas
                value:
                    query: "Explícame sobre inteligencia artificial"
                    search_type: "mmr"
                    return_sources: true
                    return_context: false
                    llm: "openai"
                    model: "gpt-4-turbo"
                    temperature: 0.5
                    max_tokens: 1000
                    session_id: "session_abc123"

                contextual_chat:
                summary: Chat con contexto de sesión
                value:
                    query: "¿Y cuál es el clima típico?"
                    session_id: "session_abc123"
                    search_type: "similarity"

            multipart/form-data:
            schema:
                type: object
                required:
                - query
                properties:
                query:
                    type: string
                    description: Pregunta o mensaje
                file:
                    type: string
                    format: binary
                    description: Archivo a procesar (PDF, TXT, MD, etc.)
                search_type:
                    type: string
                    enum: [similarity, mmr, ensemble]
                return_sources:
                    type: boolean

        responses:
        "200":
            description: Respuesta exitosa del chatbot
            content:
            application/json:
                schema:
                $ref: "#/components/schemas/ChatResponse"
                examples:
                simple_response:
                    summary: Respuesta simple
                    value:
                    response: "La mejor época para visitar Japón es durante la primavera (marzo-mayo) para ver los cerezos en flor, o en otoño (septiembre-noviembre) por el clima agradable y los colores del follaje."
                    session_id: "session_abc123"

                response_with_sources:
                    summary: Respuesta con fuentes
                    value:
                    response: "La mejor época para visitar Japón es durante la primavera..."
                    sources:
                        - content: "Japan's cherry blossom season typically occurs in March..."
                        metadata:
                            source: "japan_travel_guide.pdf"
                            page: 12
                            title: "Best Times to Visit Japan"
                        score: 0.92
                        - content: "Autumn in Japan offers spectacular foliage..."
                        metadata:
                            source: "seasonal_travel.pdf"
                            page: 5
                        score: 0.87
                    session_id: "session_abc123"
                    metadata:
                        model: "gpt-4-turbo"
                        temperature: 0.7
                        tokens_used: 245
                        response_time: 1.23

        "400":
            $ref: "#/components/responses/BadRequest"
        "401":
            $ref: "#/components/responses/Unauthorized"
        "404":
            description: Chatbot no encontrado
            content:
            application/json:
                schema:
                $ref: "#/components/schemas/ErrorResponse"
                example:
                error: "Not Found"
                message: "Chatbot 'travel_bot' not found."
        "422":
            $ref: "#/components/responses/ValidationError"
        "500":
            $ref: "#/components/responses/InternalError"

        security:
        - sessionAuth: []
        """
        app = self.request.app
        name = self.request.match_info.get('chatbot_name', None)
        method_name = self.request.match_info.get('method_name', None)
        qs = self.query_parameters(self.request)
        try:
            attachments, data = await self.handle_upload()
        except web.HTTPUnsupportedMediaType:
            # if no file is provided, then is a JSON request:
            data = await self.request.json()
            attachments = {}
        if 'llm' in qs:
            # passing another LLM to the Chatbot:
            llm = data.pop('llm')
            model = data.pop('model', None)
        else:
            llm = None
            model = None
        try:
            manager = app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        try:
            chatbot: AbstractBot = await manager.get_bot(name)
            if not chatbot:
                raise KeyError(
                    f"Chatbot {name} not found."
                )
        except (TypeError, KeyError):
            return self.json_response(
                {
                "message": f"Chatbot {name} not found."
                },
                status=404
            )
        # getting the question:
        question = data.pop('query', None)
        search_type = data.pop('search_type', 'similarity')
        return_sources = data.pop('return_sources', True)
        return_context = data.pop('return_context', False)
        try:
            session = self.request.session
        except AttributeError:
            session = None
        if not session:
            return self.json_response(
                {
                "message": "User Session is required to interact with a Chatbot."
                },
                status=400
            )
        stream = data.pop('stream', False)
        if isinstance(stream, str):
            stream = stream.lower() == 'true'
        try:
            async with chatbot.retrieval(self.request, app=app, llm=llm) as bot:
                session_id = session.get('session_id', None)
                user_id = session.get('user_id', None)
                if not session_id:
                    session_id = str(uuid.uuid4())
                if method:= self._check_methods(bot, method_name):
                    sig = inspect.signature(method)
                    method_params = {}
                    missing_required = []
                    for param_name, param in sig.parameters.items():
                        if param_name == 'self' or param_name in 'kwargs':
                            continue
                        # Handle different parameter types
                        if param.kind == inspect.Parameter.VAR_POSITIONAL:
                            # *args - skip, we don't handle positional args via JSON
                            continue
                        elif param.kind == inspect.Parameter.VAR_KEYWORD:
                            # **kwargs - pass all remaining data that wasn't matched
                            continue
                        # Regular parameters
                        if param_name in data:
                            method_params[param_name] = data[param_name]
                        elif param.default == inspect.Parameter.empty:
                            # Required parameter missing
                            missing_required.append(param_name)
                        if param_name in attachments:
                            files = attachments[param_name]
                            if hasattr(param.annotation, '__origin__'):
                                # If the parameter is a file upload, handle accordingly
                                method_params[param_name] = files
                            else:
                                method_params[param_name] = files[0] if files else None
                    if missing_required:
                        return self.json_response(
                            {
                                "message": f"Required parameters missing: {', '.join(missing_required)}",
                                "required_params": [p for p in sig.parameters.keys() if p != 'self']
                            },
                                status=400
                            )
                    try:
                        method_params = {**method_params, **data}
                        response = await method(
                            **method_params
                        )
                        if isinstance(response, web.Response):
                            return response
                        return web.json_response(
                            response, dumps=json_encoder
                        )
                    except Exception as exc:
                        self.error(
                            f"Error invoking method {method_name} on chatbot {name}: {exc}",
                            exception=exc,
                            status=400
                        )
                if not question:
                    return self.json_response(
                        {
                            "message": "Query parameter is required to interact with the chatbot."
                        },
                        status=400
                    )
                if stream:
                    response = web.StreamResponse(
                        status=200,
                        headers={
                            'Content-Type': 'text/event-stream',
                            'Cache-Control': 'no-cache',
                            'Connection': 'keep-alive'
                        }
                    )
                    await response.prepare(self.request)

                    try:
                        async for event in await bot.ask_stream(
                            question=question,
                            session_id=session_id,
                            user_id=user_id,
                            search_type=search_type,
                            llm=llm,
                            model=model,
                            return_sources=return_sources,
                            return_context=return_context,
                            request=self.request,
                            **data
                        ):
                            payload = json_encoder(event)
                            message = f"data: {payload}\n\n"
                            await response.write(message.encode('utf-8'))
                    except Exception as exc:
                        error_payload = json_encoder({
                            "event": "error",
                            "data": str(exc)
                        })
                        await response.write(f"data: {error_payload}\n\n".encode('utf-8'))
                        raise
                    finally:
                        await response.write_eof()
                    return response

                response = await bot.conversation(
                    question=question,
                    session_id=session_id,
                    user_id=user_id,
                    search_type=search_type,
                    llm=llm,
                    model=model,
                    return_sources=return_sources,
                    return_context=return_context,
                    request=self.request,
                    **data
                )
                return web.json_response(
                    response,
                    dumps=json_encoder
                )
        except ValueError as exc:
            return self.error(
                f"{exc}",
                exception=exc,
                status=400
            )
        except web.HTTPException as exc:
            return self.error(
                f"{exc}",
                exception=exc,
                status=400
            )
        except Exception as exc:
            return self.error(
                f"Error invoking chatbot {name}: {exc}",
                exception=exc,
                status=400
            )


@is_authenticated()
@user_session()
class BotHandler(BaseView):
    """BotHandler.
    description: Bot Handler for Parrot Application.
    Use this handler to interact with a brand new chatbot, consuming a configuration.
    """
    async def _create_bot(self, name: str, data: dict):
        """Create a New Bot (passing a configuration).
        """
        db = self.request.app['database']
        async with await db.acquire() as conn:
            BotModel.Meta.connection = conn
            # check first if chatbot already exists:
            exists = None
            try:
                exists = await BotModel.get(name=name)
            except NoDataFound:
                exists = False
            if exists:
                return self.json_response(
                    {
                        "message": f"Chatbot {name} already exists with id {exists.chatbot_id}"
                    },
                    status=202
                )
            try:
                chatbot_model = BotModel(
                    name=name,
                    **data
                )
                chatbot_model = await chatbot_model.insert()
                return chatbot_model
            except ValidationError:
                raise
            except Exception:
                raise

    async def put(self):
        """Create a New Bot (passing a configuration).
        """
        try:
            manager = self.request.app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        # TODO: Making a Validation of data
        data = await self.request.json()
        name = data.pop('name', None)
        if not name:
            return self.json_response(
                {
                "message": "Name for Bot Creation is required."
                },
                status=400
            )
        try:
            bot = manager.create_bot(name=name, **data)
        except Exception as exc:
            print(exc.__traceback__)
            return self.error(
                response={
                    "message": f"Error creating chatbot {name}.",
                    "exception": str(exc),
                    "stacktrace": str(exc.__traceback__)
                },
                exception=exc,
                status=400
            )
        try:
            # if bot is created:
            await self._create_bot(name=name, data=data)
        except ValidationError as exc:
            return self.error(
                f"Validation Error for {name}: {exc}",
                exception=exc.payload,
                status=400
            )
        except Exception as exc:
            print(exc.__traceback__)
            return self.error(
                response={
                    "message": f"Error creating chatbot {name}.",
                    "exception": str(exc),
                    "stacktrace": str(exc.__traceback__)
                },
                exception=exc,
                status=400
            )
        try:
            # Then Configure the bot:
            await bot.configure(app=self.request.app)
            return self.json_response(
                {
                    "message": f"Chatbot {name} created successfully."
                }
            )
        except Exception as exc:
            return self.error(
                f"Error on chatbot configuration: {name}: {exc}",
                exception=exc,
                status=400
            )


@is_authenticated()
@user_session()
class BotManagement(BaseView):
    """BotManagement.
    description: Bot Management Handler for Parrot Application.
    Use this handler to list all available chatbots, upload files, and delete chatbots.
    """
    async def get(self):
        """List all available chatbots.
        """
        try:
            manager = self.request.app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        try:
            all_bots = manager.get_bots()
            bots = []
            for bot_name, bot in all_bots.items():
                bots.append({
                    "name": bot_name,
                    "chatbot_id": bot.chatbot_id,
                    "bot_class": str(bot.__class__.__name__),
                    "description": bot.description,
                    "backstory": bot.backstory,
                    "role": bot.role,
                    "embedding_model": bot.embedding_model,
                    "llm": f"{bot.llm!r}",
                    "temperature": bot.llm.temperature,
                    "documents": bot.get_vector_store()
                })
        except Exception as exc:
            return self.error(
                response={
                    "message": f"Error retrieving chatbots.",
                    "exception": str(exc),
                    "stacktrace": str(exc.__traceback__)
                },
                exception=exc,
                status=400
            )
        return self.json_response(
            {
                "bots": bots
            }
        )

    def _get_loader(self, loader_name: Union[str, type]) -> type:
        """Get the loader class by name."""
        if isinstance(loader_name, type) and issubclass(loader_name, AbstractLoader):
            return loader_name
        if not loader_name:
            return None
        try:
            module = importlib.import_module('parrot.loaders', package=None)
            loader_cls = getattr(module, loader_name, None)
            if not loader_cls:
                raise ValueError(f"Loader not found: {loader_name}")
            if isinstance(loader_cls, type) and issubclass(loader_cls, AbstractLoader):
                return loader_cls
        except Exception:
            pass
        # try submodule guess
        base = loader_name[:-6] if loader_name.endswith("Loader") else loader_name
        candidates = [
            f"parrot.loaders.{base.lower()}",
            f"parrot.loaders.{re.sub(r'(?<!^)(?=[A-Z])','_',base).lower()}",
        ]
        for mod_name in candidates:
            try:
                mod = importlib.import_module(mod_name)
                loader_cls = getattr(mod, loader_name, None)
                if isinstance(loader_cls, type) and issubclass(loader_cls, AbstractLoader):
                    return loader_cls
            except Exception:
                continue
        return None

    def _group_attachments_by_loader(self, attachments, default_loader_cls=None):
        """
        Returns dict[LoaderClass, list[Path]]
        If default_loader_cls is provided, all files go to that loader.
        Otherwise, choose per-file from AVAILABLE_LOADERS by extension, fallback to MarkdownLoader.
        """
        by_loader = defaultdict(list)
        files = []
        for _, values in attachments.items():
            for a in values or []:
                p = a.get("file_path")
                if p is None:
                    continue
                files.append(Path(p))

        if default_loader_cls:
            if not issubclass(default_loader_cls, AbstractLoader):
                raise TypeError(
                    f"Default loader must subclass AbstractLoader, got {default_loader_cls}"
                )
            if files:
                by_loader[default_loader_cls].extend(files)
            return by_loader

        # No default → pick by extension
        for p in files:
            ext = p.suffix.lower()
            loader_cls = AVAILABLE_LOADERS.get(ext, MarkdownLoader)
            by_loader[loader_cls].append(p)

        return by_loader

    async def put(self):
        """Upload a file to a chatbot.
        """
        try:
            attachments, form_data = await self.handle_upload()
        except web.HTTPUnsupportedMediaType:
            # if no file is provided, then is a JSON request:
            form_data = await self.request.json()
            attachments = {}
        try:
            manager = self.request.app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        params = self.get_arguments(self.request)
        chatbot_name = params.get('bot', None)
        if not chatbot_name:
            return self.json_response(
                {
                    "message": "Chatbot name is required."
                },
                status=400
            )
        try:
            manager = self.request.app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        try:
            chatbot: AbstractBot = await manager.get_bot(chatbot_name)
            if not chatbot:
                raise KeyError(
                    f"Chatbot {chatbot_name} not found."
                )
        except (TypeError, KeyError):
            return self.json_response(
                {
                "message": f"Chatbot {chatbot_name} not found."
                },
                status=404
            )
        # Check if Store is loaded, if not, return error:
        if not chatbot.get_vector_store():
            return self.json_response(
                {
                    "message": f"Chatbot {chatbot_name} has no Vector Store configured."
                },
                status=400
            )
        # Check if chatbot.store is available:
        if chatbot.store is None:
            # Load the store:
            try:
                store = chatbot.get_vector_store()
                # change "name" to "vector_vector_store"
                if 'name' in store:
                    store['vector_store'] = store.pop('name')
                chatbot.define_store(
                    **store
                )
                chatbot.configure_store()
            except Exception as e:
                return self.json_response(
                    {
                        "message": f"Failed to configure store for chatbot {chatbot_name}: {e}"
                    },
                    status=500
                )
        default_loader = form_data.pop('loader', 'MarkdownLoader')
        source_type = form_data.pop('source_type', 'file')
        # Any extra kwargs for loaders (excluding 'loader' key)
        loader_kwargs = {k: v for k, v in (form_data or {}).items() if k != "loader"}
        loader_cls = self._get_loader(default_loader)
        # --- Group all attachments by loader ---
        by_loader = self._group_attachments_by_loader(
            attachments,
            default_loader_cls=loader_cls
        )
        files_list = []
        loaders_used = []
        if not by_loader and not attachments:
            # if no files were uploaded, using the form_data as a source:
            source = form_data.pop('source', None)
            # Any extra kwargs for loaders (excluding control keys)
            loader_kwargs = {k: v for k, v in (form_data or {}).items()
                if k not in {'loader', 'source_type', 'source'}}
            if not source:
                return self.json_response(
                    {"message": "No files/URLs were uploaded and no source provided."},
                    status=400
                )
            # If loader not resolved, try to infer: YouTube vs Web
            if loader_cls is None:
                if any('youtu' in u for u in source):
                    loader_cls = self._get_loader('YoutubeLoader')
                else:
                    loader_cls = self._get_loader('WebLoader')
            documents: list = []
            errors: list = []
            if loader_cls is None:
                return self.json_response(
                    {"message": "Loader not found or not specified for URL sources."},
                    status=400
                )
            try:
                loader = loader_cls(
                    source=source,
                    source_type=source_type,
                    **loader_kwargs
                )
                docs = await loader.load()
                if isinstance(docs, list):
                    documents.extend(docs)
            except Exception as exc:
                errors.append(str(exc))
            loaders_used = [loader_cls.__name__]
            files_list = source
        if attachments:
            if not by_loader:
                return self.json_response(
                    {"message": "No supported files found."},
                    status=400
                )
            tasks = []
            for loader_cls, files in by_loader.items():
                print(
                    f"Loading {len(files)} files with {loader_cls.__name__}"
                )
                try:
                    # Each loader receives the full list for that type (avoid per-file loops)
                    loader = loader_cls(
                        source=files,
                        source_type=source_type,
                        **loader_kwargs
                    )
                    tasks.append(loader.load())
                except Exception as exc:
                    return self.error(
                        f"Error initializing {loader_cls} for chatbot {chatbot_name}: {exc}",
                        exception=exc,
                        status=400
                    )
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # Flatten and handle errors without aborting the whole batch
                documents = []
                errors = []
                try:
                    for res in results:
                        if isinstance(res, Exception):
                            errors.append(str(res))
                        elif isinstance(res, list):
                            documents.extend(res)
                except Exception as exc:
                    return self.error(
                        f"Error adding documents to chatbot {chatbot_name}: {exc}",
                        exception=exc,
                        status=400
                    )
            files_list = []
            for _, values in attachments.items():
                for a in values or []:
                    p = a.get("file_path")
                    if p is None:
                        continue
                    files_list.append(str(p))
            loaders_used = [cls.__name__ for cls in by_loader.keys()]
        # Load documents into the chatbot
        try:
            if documents:
                await chatbot.store.add_documents(documents)
        except Exception as exc:
            return self.error(
                f"Error adding documents to chatbot {chatbot_name}: {exc}",
                exception=exc,
                status=400
            )
        payload = {
            "bot": chatbot_name,
            "files": files_list,
            "loaders": loaders_used,
            "documents": len(documents),
            "errors": errors,
        }
        return self.json_response(
            payload,
            status=207 if errors else 200
        )
