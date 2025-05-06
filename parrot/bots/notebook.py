"""
NotebookAgent - Specialized agent for handling Word documents, converting to Markdown,
and generating narrated summaries.
"""
import os
import re
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Union
from langchain.agents import create_openai_tools_agent
from langchain.agents.agent import AgentExecutor
from langchain.tools import BaseTool
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from langchain_core.messages import AIMessage
from langchain.prompts import SystemMessagePromptTemplate

from navconfig import BASE_DIR
from parrot.conf import BASE_STATIC_URL
from parrot.tools import WordToMarkdownTool, GoogleVoiceTool
from parrot.tools.abstract import AbstractTool
from parrot.utils import SafeDict
from parrot.models import AgentResponse

from .agent import BasicAgent

# Define format instructions directly instead of importing
FORMAT_INSTRUCTIONS = """
FORMAT INSTRUCTIONS:
When responding to user queries, follow these formatting guidelines:
1. Use markdown for structured responses
2. Use bullet points for lists
3. Use headers for sections (# for main headers, ## for subheaders)
4. Include code blocks with triple backticks when showing code
5. Format tables using markdown table syntax
6. For document analysis, highlight key findings and insights
7. When generating summaries, organize by main themes or sections
"""

# Define system prompts for document processing
NOTEBOOK_PROMPT_PREFIX = """
You are a professional document assistant named {name}, specialized in analysis, summarization, and extraction of key information from text documents. You have access to the following tools:

**Answer the following questions as best you can. You have access to the following tools:**

- {tools}\n

Use these tools effectively to provide accurate and comprehensive document analysis:
{list_of_tools}

Current date: {today_date}

{system_prompt_base}

{rationale}

## Document Analysis Capabilities

When analyzing documents, follow these comprehensive guidelines:

1. **Document Conversion and Processing**
   - Use the word_to_markdown_tool to convert Word documents to Markdown format
   - Process the resulting markdown to identify structure, sections, and key elements
   - Preserve document formatting and structure when relevant to understanding

2. **Content Analysis**
   - Identify key themes, topics, and main arguments in the document
   - Extract important facts, figures, quotes, and statistics
   - Recognize patterns in the content and logical structure
   - Analyze tone, style, and language used in the document

3. **Summarization Techniques**
   - Create executive summaries capturing the essential points
   - Develop section-by-section summaries for longer documents
   - Use bullet points for key takeaways
   - Preserve the author's original intent and meaning
   - Highlight the most important insights and conclusions

4. **Audio Narration**
   - When requested, generate clear, well-structured audio summaries
   - Format text for natural-sounding speech using GoogleVoiceTool
   - Structure narration with clear introduction, body, and conclusion
   - Use transitions between major points and sections
   - Emphasize key information through pacing and structure

5. **Special Document Elements**
   - Properly handle tables, charts, and figures by describing their content
   - Extract and process lists, bullet points, and numbered items
   - Identify and analyze headers, footers, and metadata
   - Process citations, references, and bibliographic information

6. **Output Formatting**
   - Use markdown formatting for structured responses
   - Organize information hierarchically with headers and subheaders
   - Present extracted information in tables when appropriate
   - Use code blocks for technical content or examples
   - Highlight key quotes or important excerpts

If a document is complex or lengthy, break it down into logical sections for better analysis. Always preserve the original meaning and context of the document while making the content more accessible to the user.

To analyze a document, first convert it from Word to Markdown using the word_to_markdown_tool, then work with the markdown content to provide your analysis, summary, or narration.

When asked to generate an audio summary, follow these steps:
1. Create a clear, concise summary of the document
2. Structure the summary for verbal presentation
3. Use the GoogleVoiceTool to generate the audio narration
4. Return both the text summary and the audio file information

{format_instructions}

Always begin by understanding what the user wants to do with their document. Ask for clarification if needed.
Be helpful, professional, and thorough in your document analysis.
"""

NOTEBOOK_PROMPT_SUFFIX = """
Always begin by understanding what the user wants to do with their document. Ask for clarification if needed.
Be helpful, professional, and thorough in your document analysis.
"""


class NotebookAgent(BasicAgent):
    """
    An agent specialized for working with documents - converting Word docs to Markdown,
    analyzing content, and generating narrated summaries.
    """

    def __init__(
        self,
        name: str = 'Document Assistant',
        agent_type: str = None,
        llm: Optional[str] = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        document_url: Optional[str] = None,
        **kwargs
    ):
        self._document_url = document_url
        self._document_content = None
        self._document_metadata = {}

        # Agent ID and configuration
        self._prompt_prefix = NOTEBOOK_PROMPT_PREFIX
        self._prompt_suffix = NOTEBOOK_PROMPT_SUFFIX
        self._prompt_template = prompt_template
        self._capabilities: str = kwargs.get('capabilities', None)
        self._format_instructions: str = kwargs.get('format_instructions', FORMAT_INSTRUCTIONS)

        self.name = name or "Document Assistant"
        self.description = "An agent specialized for working with documents, converting Word to Markdown, and generating narrated summaries."

        # Set up directories for outputs
        self._static_path = BASE_DIR.joinpath('static')
        self.agent_audio_dir = self._static_path.joinpath('audio', 'agents')
        self.agent_docs_dir = self._static_path.joinpath('docs', 'agents')

        # Convert string to SystemMessagePromptTemplate
        system_prompt_text = system_prompt or self.default_backstory()
        self.system_prompt = SystemMessagePromptTemplate.from_template(system_prompt_text)

        # Note: NO system_prompt is passed to the parent constructor
        super().__init__(
            name=name,
            llm=llm,
            human_prompt=human_prompt,
            tools=tools or [],
            **kwargs
        )
        # Define agent type
        self.agent_type = agent_type or "react"

    async def configure(self, document_url: str = None, app=None) -> None:
        """Configure the NotebookAgent with necessary tools and setup."""
        await super().configure(app)

        # Set document URL if provided
        if document_url:
            self._document_url = document_url

        # Initialize document processing tools if not already present
        self._init_tools()

        # Similar a PandasAgent: usa agent_type para decidir
        if self.agent_type == 'openai':
            self.agent = self.openai_agent()
        elif self.agent_type == 'openai-tools':
            self.agent = self.openai_tools_agent()
        else:
            # Fallback a react para compatibilidad con todos los modelos
            self.agent = self.react_agent()

        # Create executor from agent
        self._agent = self.get_executor(self.agent, self.tools)

    def _define_prompt(self):
        """Define the prompt for the agent with document-specific formatting."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        list_of_tools = ""
        for tool in self.tools:
            name = tool.name
            description = tool.description
            list_of_tools += f'- {name}: {description}\n'
        list_of_tools += "\n"

        # Base prompts components
        format_instructions = self._format_instructions or FORMAT_INSTRUCTIONS
        rationale = self._capabilities or ""

        # Format the prompt template with our specific values
        final_prompt = self._prompt_prefix.format_map(
            SafeDict(
                today_date=now,
                list_of_tools=list_of_tools,
                system_prompt_base=self.default_backstory(),
                format_instructions=format_instructions,
                rationale=rationale,
                name=self.name,
                tools=", ".join([tool.name for tool in self.tools])
            )
        )

        # Create the chat prompt template
        from langchain.prompts import (
            ChatPromptTemplate,
            SystemMessagePromptTemplate,
            HumanMessagePromptTemplate,
            MessagesPlaceholder
        )

        # Define a structured system message
        system_message = f"""
        Today is {now}. You are {self.name}, a document processing assistant.
        Your job is to help users analyze documents, extract information, and generate summaries.

        When working with documents, first convert them using the word_to_markdown_tool,
        then analyze the content and provide insights or summaries as requested.
        """

        # Important: Add agent_scratchpad to the prompt
        chat_prompt = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_message),
            HumanMessagePromptTemplate.from_template(final_prompt),
            # Add a placeholder for the agent's scratchpad/intermediate steps
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

        self.prompt = chat_prompt.partial(
            tools=self.tools,
            tool_names=", ".join([tool.name for tool in self.tools]),
            name=self.name
        )

    async def load_document(self, url: str) -> Dict[str, Any]:
        """
        Load a document from a URL using WordToMarkdownTool.

        Args:
            url: URL of the Word document to load

        Returns:
            Dictionary with document content and metadata
        """
        if not url:
            return {"error": "No document URL provided"}

        word_tool = next((tool for tool in self.tools if tool.name == "word_to_markdown_tool"), None)

        if not word_tool:
            return {"error": "WordToMarkdownTool not available"}

        try:
            # Use the tool to load and convert the document
            result = await word_tool._arun(url)

            if not result.get("success", False):
                return {"error": result.get("error", "Unknown error loading document")}

            self._document_content = result.get("markdown", "")
            self._document_metadata = {
                "source_url": url,
                "loaded_at": datetime.now().isoformat(),
                "format": "markdown"
            }

            return {
                "content": self._document_content,
                "metadata": self._document_metadata,
                "success": True
            }
        except Exception as e:
            return {"error": f"Error loading document: {str(e)}"}

    async def generate_summary_direct(self, max_length: int = 500) -> Dict[str, Any]:
        """Generate a summary directly using the LLM without the agent."""
        if not self._document_content:
            print("Error: No document content available to summarize")
            return {"error": "No document content available to summarize"}

        # Añadir un mensaje de depuración para ver el contenido del documento
        content_length = len(self._document_content)
        print(f"Generating summary directly with LLM for document with {content_length} characters")

        try:
            # Create a more robust summarization prompt
            prompt = f"""
            I need you to analyze this document and create a clear summary.

            {self._document_content[:10000]}

            Please provide a comprehensive summary that:
            1. Captures the main points and themes
            2. Is well-structured with headers for major sections
            3. Uses bullet points for key details when appropriate
            4. Is suitable for audio narration

            Focus on providing value and clarity in your summary.
            """

            # Use direct invocation to debug the response
            print("Sending prompt to LLM...")
            print(f"Prompt preview: {prompt[:100]}...")

            # Usar el LLM directamente (no el agente)
            summary_text = await self._llm.ainvoke(prompt)

            if not summary_text:
                print("Warning: Generated summary is empty!")
                return {"error": "Failed to generate summary"}

            print(f"Summary generated, length: {len(summary_text)} characters")

            # Generate audio from the summary
            print("Generating audio...")
            audio_info = await self._generate_audio(summary_text)

            return {
                "summary": summary_text,
                "audio": audio_info,
                "success": True
            }
        except Exception as e:
            import traceback
            print(f"Error generating summary: {str(e)}")
            print(traceback.format_exc())
            return {"error": f"Error generating summary: {str(e)}"}

    async def _preprocess_text_for_speech(self, text: str) -> str:
        """
        Preprocesa el texto Markdown para convertirlo en texto conversacional para podcast.
        Elimina marcas de formato pero preserva el flujo natural del discurso.

        Args:
            text: Texto en formato Markdown

        Returns:
            Texto fluido y conversacional optimizado para síntesis de voz
        """
        # Remover marcas de negrita/cursiva sin agregar texto explicativo
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # Quitar **negrita**
        text = re.sub(r'\*(.*?)\*', r'\1', text)      # Quitar *cursiva*
        text = re.sub(r'__(.*?)__', r'\1', text)      # Quitar __negrita__
        text = re.sub(r'_(.*?)_', r'\1', text)        # Quitar _cursiva_

        # Mejorar listas para que suenen naturales (sin "Punto:")
        text = re.sub(r'^\s*[\*\-\+]\s+', '', text, flags=re.MULTILINE)  # Listas sin orden
        text = re.sub(r'^\s*(\d+)\.\s+', '', text, flags=re.MULTILINE)   # Listas numeradas

        # Convertir encabezados manteniendo el texto original (sin "Sección:")
        text = re.sub(r'^#{1,6}\s+(.*)', r'\1', text, flags=re.MULTILINE)

        # Limpiar otros elementos Markdown
        text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)  # Enlaces: solo texto
        text = re.sub(r'`(.*?)`', r'\1', text)           # Quitar texto en `código`
        text = re.sub(r'~~(.*?)~~', r'\1', text)         # Quitar ~~tachado~~

        # Eliminar bloques de código que no son relevantes para audio
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

        # Eliminar caracteres especiales innecesarios para voz
        text = re.sub(r'[|]', ' ', text)  # Quitar pipes (comunes en tablas)

        # Tratar con dobles puntos y viñetas para mejor fluidez
        text = re.sub(r':\s*\n', '. ', text)  # Convertir ":" seguido de salto de línea en punto

        # Agregar pausas naturales después de párrafos para respiración
        text = re.sub(r'\n{2,}', '. ', text)  # Convertir múltiples saltos en pausa

        # Normalizar espacios y puntuación para mejor fluidez
        text = re.sub(r'\s{2,}', ' ', text)      # Limitar espacios consecutivos
        text = re.sub(r'\.{2,}', '.', text)      # Convertir múltiples puntos en uno solo
        text = re.sub(r'\.\s*\.', '.', text)     # Eliminar dobles puntos consecutivos

        # Mejorar la transición entre oraciones
        text = re.sub(r'([.!?])\s+([A-Z])', r'\1 \2', text)  # Asegurar espacio después de puntuación

        print(f"Texto preprocesado para síntesis de voz. Longitud original: {len(text)}, nueva: {len(text)}")

        # Opcional: Agregar instrucciones sutiles de narración si es necesario
        # text = "En este resumen: " + text

        return text

    async def _generate_audio(self, text: str, voice_gender: str = "FEMALE") -> Dict[str, Any]:
        """
        Generate audio narration from text using GoogleVoiceTool.

        Args:
            text: Text to convert to audio
            voice_gender: Gender of the voice (MALE or FEMALE)

        Returns:
            Dictionary with audio file information
        """
        try:
            # Find the voice tool
            voice_tool = next((tool for tool in self.tools if tool.name == "podcast_generator_tool"), None)

            if not voice_tool:
                print("Voice tool not found! Available tools: " + ", ".join([t.name for t in self.tools]))
                return {}

            # Ensure output directory exists
            os.makedirs(str(self.agent_audio_dir), exist_ok=True)

            # Preprocesar el texto para eliminar caracteres de Markdown y mejorar la lectura
            print("Preprocesando texto para síntesis de voz...")
            processed_text = await self._preprocess_text_for_speech(text)

            print(f"Generating audio using voice tool (direct query)...")

            # Pasar el texto preprocesado directamente
            result = await voice_tool._arun(query=processed_text)

            # Process result
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except:
                    result = {"message": result}

            print(f"Voice tool result: {result}")

            # Verificar que el archivo exista
            if "file_path" in result and os.path.exists(result["file_path"]):
                file_path = result["file_path"]
                # URL relativa para acceso web - CORREGIDO
                url = str(file_path).replace(str(self._static_path), BASE_STATIC_URL)
                result["url"] = url
                result["filename"] = os.path.basename(file_path)
                print(f"Audio generated successfully at: {file_path}")
                print(f"Audio URL: {url}")
            else:
                print(f"Audio file path not found in result or file doesn't exist")
                if "file_path" in result:
                    print(f"Expected path was: {result['file_path']}")
                if "error" in result:
                    print(f"Error reported by tool: {result['error']}")

            return result
        except Exception as e:
            import traceback
            print(f"Error generating audio: {e}")
            print(traceback.format_exc())
            return {}

    def extract_filenames(self, response: AgentResponse) -> Dict[str, Dict[str, Any]]:
        """Extract filenames from the content."""
        # Split the content by lines
        output_lines = response.output.splitlines()
        current_filename = ""
        filenames = {}

        for line in output_lines:
            if 'filename:' in line:
                current_filename = line.split('filename:')[1].strip()
                if current_filename:
                    try:
                        filename_path = Path(current_filename).resolve()
                        if filename_path.is_file():
                            content_type = self.mimefromext(filename_path.suffix)
                            url = str(filename_path).replace(str(self._static_path), BASE_STATIC_URL)
                            filenames[filename_path.name] = {
                                'content_type': content_type,
                                'file_path': filename_path,
                                'filename': filename_path.name,
                                'url': url
                            }
                        continue
                    except AttributeError:
                        pass

        if filenames:
            response.filename = filenames

        return filenames

    def mimefromext(self, ext: str) -> str:
        """Get the mime type from the file extension."""
        mime_types = {
            '.csv': 'text/csv',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.json': 'application/json',
            '.txt': 'text/plain',
            '.html': 'text/html',
            '.htm': 'text/html',
            '.pdf': 'application/pdf',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml',
            '.md': 'text/markdown',
            '.ogg': 'audio/ogg',
            '.wav': 'audio/wav',
            '.mp3': 'audio/mpeg',
            '.mp4': 'video/mp4',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }
        return mime_types.get(ext, 'application/octet-stream')

    def default_backstory(self) -> str:
        return "You are a helpful document assistant built to provide analysis, summaries, and insights from text documents. You can convert Word documents to Markdown and generate audio summaries."

    def _init_tools(self):
        """Initialize tools needed for document processing."""
        # Check if we already have required tools
        has_word_tool = any(tool.name == "word_to_markdown_tool" for tool in self.tools)
        has_voice_tool = any(tool.name == "podcast_generator_tool" for tool in self.tools)

        # Add WordToMarkdownTool if not present
        if not has_word_tool:
            word_tool = WordToMarkdownTool()
            self.tools.append(word_tool)

        # Add GoogleVoiceTool if not present
        if not has_voice_tool:
            voice_tool = GoogleVoiceTool()
            print(f"Added voice tool with name: {voice_tool.name}")
            self.tools.append(voice_tool)

        # Log the tools we're using
        tool_names = [tool.name for tool in self.tools]
        print(f"NotebookAgent initialized with tools: {', '.join(tool_names)}")

    async def process_document_workflow(self, document_url: str) -> Dict[str, Any]:
        """
        Run a complete document processing workflow:
        1. Load and convert document
        2. Generate a summary
        3. Create an audio narration

        Args:
            document_url: URL to the Word document

        Returns:
            Dictionary with document content, summary, and audio information
        """
        # Step 1: Load the document
        document_result = await self.load_document(document_url)

        if "error" in document_result:
            return document_result

        # Step 2: Generate summary and audio using direct method
        try:
            summary_result = await self.generate_summary_direct()
        except Exception as e:
            print(f"Error in direct summary generation: {e}")
            summary_result = {"error": str(e), "summary": "", "audio": {}}

        # Combine results
        return {
            "document": {
                "content": self._document_content[:500] + "..." if len(self._document_content) > 500 else self._document_content,
                "metadata": self._document_metadata
            },
            "summary": summary_result.get("summary", ""),
            "audio": summary_result.get("audio", {}),
            "success": True
        }

    def react_agent(self):
        """Create a ReAct agent for better compatibility with different LLMs."""
        from langchain.agents import create_react_agent

        # Define a prompt template for the agent
        agent = create_react_agent(
            llm=self._llm,
            tools=self.tools,
            prompt=self.prompt
        )
        return agent

    def openai_tools_agent(self):
        """Create an OpenAI Tools agent - this is the original method."""
        from langchain.agents import create_openai_tools_agent

        agent = create_openai_tools_agent(
            self._llm,
            self.tools,
            self.prompt
        )
        return agent

    def get_executor(self, agent, tools):
        """Create an agent executor with proper output keys."""
        from langchain.agents.agent import AgentExecutor

        # Creamos el executor con una clave de salida definida
        return AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=tools,
            verbose=True,
            return_intermediate_steps=True,
            output_keys=["output"],  # Define explícitamente la clave de salida
        )
