"""
OpenAPI Configuration for AI-Parrot
====================================

Configure aiohttp-swagger3 with complete OpenAPI 3.0 schemas for all handlers.
"""
from pathlib import Path
from aiohttp import web
from aiohttp_swagger3 import (
    SwaggerDocs,
    SwaggerInfo,
    SwaggerContact,
    SwaggerLicense,
    SwaggerUiSettings,
    ReDocUiSettings,
    RapiDocUiSettings
)


def setup_swagger(app: web.Application) -> web.Application:
    """
    Configure Swagger/OpenAPI documentation for AI-Parrot.

    Enables three UI options:
    - Swagger UI at /api/docs
    - ReDoc at /api/docs/redoc
    - RapiDoc at /api/docs/rapidoc

    Args:
        app: aiohttp Application instance

    Returns:
        Configured application with documentation endpoints
    """

    # Define API Information
    swagger_info = SwaggerInfo(
        title="AI-Parrot API",
        version="1.0.0",
        description="""
# AI-Parrot: Multi-Agent & Chatbot Platform

AI-Parrot es una plataforma completa para trabajar con LLMs, agentes y chatbots.

## Características principales

- 🤖 **Chatbots inteligentes** con RAG y memoria conversacional
- 🎯 **Agentes autónomos** con herramientas y MCP servers
- 🔄 **Orquestación de crews** para tareas complejas
- 💾 **Vector stores** con PgVector para búsqueda semántica
- 🔧 **Toolkits extensibles** para integración con sistemas externos
- 📊 **Structured outputs** con validación Pydantic

## Clientes LLM soportados

- Google GenAI (Gemini)
- OpenAI (GPT-4, GPT-3.5)
- Anthropic Claude
- Groq

## Arquitectura REST

Todos los endpoints siguen convenciones RESTful estándar:
- `GET` - Obtener información
- `POST` - Crear o ejecutar acciones
- `PUT` - Crear recursos
- `PATCH` - Actualizar recursos parcialmente
- `DELETE` - Eliminar recursos

## Autenticación

La mayoría de endpoints requieren autenticación mediante session cookies.
Algunos endpoints administrativos requieren privilegios de superuser.
        """,
        contact=SwaggerContact(
            name="AI-Parrot Development Team",
            url="https://github.com/phenobarbital/ai-parrot",
            email="support@ai-parrot.dev"
        ),
        license=SwaggerLicense(
            name="MIT License",
            url="https://opensource.org/licenses/MIT"
        ),
        terms_of_service="https://github.com/phenobarbital/ai-parrot/blob/main/TERMS.md"
    )

    # Configure Swagger UI (familiar interface for developers)
    swagger_ui_settings = SwaggerUiSettings(
        path="/api/docs",
        docExpansion="list",  # 'list', 'full', 'none'
        filter=True,  # Enable search filter
        deepLinking=True,  # Enable deep linking for tags and operations
        displayRequestDuration=True,  # Show request duration
        defaultModelsExpandDepth=3,  # Expand models by default
        defaultModelExpandDepth=3,
        showExtensions=True,
        showCommonExtensions=True
    )

    # Configure ReDoc (beautiful, professional documentation)
    redoc_ui_settings = ReDocUiSettings(
        path="/api/docs/redoc",
        expandResponses="200,201",  # Auto-expand successful responses
        jsonSampleExpandLevel=3,  # Expand JSON examples
        hideDownloadButton=False,
        disableSearch=False,
        hideHostname=False,
        expandSingleSchemaField=True,
        menuToggle=True,
        sortPropsAlphabetically=True,
        payloadSampleIdx=0,  # Show first example by default
    )

    # Configure RapiDoc (modern, customizable with dark mode)
    rapidoc_ui_settings = RapiDocUiSettings(
        path="/api/docs/rapidoc",
        theme="dark",  # 'light' or 'dark'
        render_style="focused",  # 'read', 'view', 'focused'
        schema_style="tree",  # 'tree' or 'table'
        layout="column",  # 'row' or 'column'
        allow_try=True,  # Enable "Try it out"
        allow_authentication=True,
        allow_spec_url_load=False,
        allow_spec_file_load=False,
        heading_text="AI-Parrot API Documentation",
        show_header=True,
        show_info=True,
        use_path_in_nav_bar=True,
        nav_bg_color="#1e1e1e",
        nav_text_color="#ffffff",
        nav_hover_bg_color="#333333",
        primary_color="#4CAF50",
        font_size="default",
    )

    # Initialize SwaggerDocs
    current_dir = Path(__file__).parent
    components_path = current_dir / "components.yaml"

    swagger = SwaggerDocs(
        app,
        info=swagger_info,
        swagger_ui_settings=swagger_ui_settings,
        redoc_ui_settings=redoc_ui_settings,
        rapidoc_ui_settings=rapidoc_ui_settings,
        components=str(components_path),  # External components file
        validate=True,  # Validate requests against schema
        request_key="swagger_dict",  # Key to store validated data in request
    )

    return app


def get_common_responses():
    """
    Common HTTP responses used across all endpoints.

    Returns:
        Dict of reusable response definitions
    """
    return {
        "400": {
            "description": "Bad Request - Invalid input parameters",
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/ErrorResponse"
                    },
                    "example": {
                        "error": "Bad Request",
                        "message": "Invalid JSON in request body",
                        "details": {}
                    }
                }
            }
        },
        "401": {
            "description": "Unauthorized - Authentication required",
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/ErrorResponse"
                    },
                    "example": {
                        "error": "Unauthorized",
                        "message": "Valid session required"
                    }
                }
            }
        },
        "403": {
            "description": "Forbidden - Insufficient permissions",
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/ErrorResponse"
                    },
                    "example": {
                        "error": "Forbidden",
                        "message": "Superuser privileges required"
                    }
                }
            }
        },
        "404": {
            "description": "Not Found - Resource does not exist",
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/ErrorResponse"
                    },
                    "example": {
                        "error": "Not Found",
                        "message": "Chatbot 'my_bot' not found"
                    }
                }
            }
        },
        "422": {
            "description": "Unprocessable Entity - Validation error",
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/ValidationErrorResponse"
                    },
                    "example": {
                        "error": "Validation Error",
                        "message": "Input validation failed",
                        "errors": [
                            {
                                "loc": ["body", "temperature"],
                                "msg": "ensure this value is less than or equal to 2.0",
                                "type": "value_error"
                            }
                        ]
                    }
                }
            }
        },
        "500": {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/ErrorResponse"
                    },
                    "example": {
                        "error": "Internal Server Error",
                        "message": "An unexpected error occurred"
                    }
                }
            }
        }
    }


def get_security_schemes():
    """
    Security schemes for API authentication.

    Returns:
        Dict of security scheme definitions
    """
    return {
        "sessionAuth": {
            "type": "apiKey",
            "in": "cookie",
            "name": "session",
            "description": "Session-based authentication using HTTP cookies"
        },
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token authentication"
        }
    }


# Tags for organizing endpoints
TAGS_METADATA = [
    {
        "name": "chatbots",
        "description": "Operaciones relacionadas con chatbots - interacción y consulta de información",
        "externalDocs": {
            "description": "Chatbot documentation",
            "url": "https://github.com/phenobarbital/ai-parrot/blob/main/docs/chatbots.md"
        }
    },
    {
        "name": "bot-management",
        "description": "Gestión CRUD de bots/agents - crear, listar, actualizar, eliminar",
        "externalDocs": {
            "description": "Bot management guide",
            "url": "https://github.com/phenobarbital/ai-parrot/blob/main/docs/bot-management.md"
        }
    },
    {
        "name": "agents",
        "description": "Interacción con agentes autónomos - conversaciones con soporte para tools y MCP",
        "externalDocs": {
            "description": "Agent documentation",
            "url": "https://github.com/phenobarbital/ai-parrot/blob/main/docs/agents.md"
        }
    },
    {
        "name": "crews",
        "description": "Orquestación de crews multi-agente para tareas complejas",
        "externalDocs": {
            "description": "Crew orchestration guide",
            "url": "https://github.com/phenobarbital/ai-parrot/blob/main/docs/crews.md"
        }
    },
    {
        "name": "tools",
        "description": "Registro y gestión de herramientas para agentes",
    },
    {
        "name": "feedback",
        "description": "Sistema de feedback para mejorar respuestas de bots",
    }
]
