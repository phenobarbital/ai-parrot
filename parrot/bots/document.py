"""
DocumentAgent - Specialized agent for document processing without Langchain.

Migrated from NotebookAgent to use native Parrot architecture:
- Extends BasicAgent from parrot.bots.agent
- Uses AbstractTool-based tools (WordToMarkdownTool, GoogleVoiceTool, ExcelTool)
- Native conversation() and invoke() methods
- Async-first architecture
- Integrated with ToolManager
"""
import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Union
from navconfig import BASE_DIR
from navconfig.logging import logging

from parrot.conf import BASE_STATIC_URL
from parrot.bots.agent import BasicAgent
from parrot.tools.abstract import AbstractTool
from parrot.tools.excel import ExcelTool
from parrot.tools.msword import WordToMarkdownTool, MSWordTool
from parrot.tools.gvoice import GoogleVoiceTool
from parrot.models.responses import AIMessage, AgentResponse


# Define format instructions
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


# System prompt for document processing
DOCUMENT_AGENT_SYSTEM_PROMPT = """You are {name}, a document assistant specialized in analysis,
summarization, and extraction of key information from text documents.

Current date: {today_date}

## Your Capabilities

You have access to the following tools:
{tools_list}

## Document Analysis Guidelines

When analyzing documents, follow these comprehensive guidelines:

1. **Document Conversion and Processing**
   - Use word_to_markdown_tool to convert Word documents to Markdown format
   - Use excel_tool to work with Excel spreadsheets
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
   - Format text for natural-sounding speech using google_tts_service tool
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

{format_instructions}

Always begin by understanding what the user wants to do with their document.
Ask for clarification if needed. Be helpful, professional, and thorough in your document analysis.
"""


class DocumentAgent(BasicAgent):
    """
    A specialized agent for document processing - converting Word docs to Markdown,
    analyzing content, processing Excel files, and generating narrated summaries.

    This agent extends BasicAgent and integrates document-specific tools without
    relying on Langchain dependencies.
    """

    def __init__(
        self,
        name: str = 'Document Assistant',
        llm: Optional[str] = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        document_url: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize the DocumentAgent.

        Args:
            name: Agent name
            llm: LLM client to use (e.g., 'google', 'openai', 'anthropic')
            tools: List of tools to use (will add document tools automatically)
            system_prompt: Custom system prompt (uses default if None)
            document_url: Optional URL to a document to process
            **kwargs: Additional arguments for BasicAgent
        """
        self._document_url = document_url
        self._document_content = None
        self._document_metadata = {}

        # Format instructions
        self._format_instructions: str = kwargs.pop('format_instructions', FORMAT_INSTRUCTIONS)

        # Set up directories for outputs
        self._static_path = BASE_DIR.joinpath('static', self.agent_id)
        self.agent_audio_dir = self._static_path.joinpath('audio', 'agents')
        self.agent_docs_dir = self._static_path.joinpath('docs', 'agents')

        # Ensure directories exist
        os.makedirs(str(self.agent_audio_dir), exist_ok=True)
        os.makedirs(str(self.agent_docs_dir), exist_ok=True)

        # Initialize logger
        self.logger = logging.getLogger(f'Parrot.DocumentAgent.{name}')

        # Initialize tools list if None
        if tools is None:
            tools = []

        # Add document-specific tools
        self._init_document_tools(tools)

        # Create system prompt
        if system_prompt is None:
            system_prompt = self._create_system_prompt()

        # Initialize parent BasicAgent
        super().__init__(
            name=name,
            llm=llm,
            system_prompt=system_prompt,
            tools=tools,
            **kwargs
        )

        self.description = (
            "A specialized agent for document processing, analysis, and summarization. "
            "Can convert Word documents to Markdown, process Excel files, and generate audio summaries."
        )

    def _init_document_tools(self, tools: List[AbstractTool]) -> None:
        """Initialize document-specific tools if not already present."""
        # Check existing tools
        tool_names = {tool.name for tool in tools}

        # Add MSWordTool if not present
        if "ms_word_tool" not in tool_names:
            try:
                msword_tool = MSWordTool(
                    output_dir=str(self.agent_docs_dir)
                )
                tools.append(msword_tool)
                self.logger.info("Added MSWordTool")
            except Exception as e:
                self.logger.warning(f"Could not add MSWordTool: {e}")

        # Add WordToMarkdownTool if not present
        if "word_to_markdown_tool" not in tool_names:
            try:
                word_tool = WordToMarkdownTool()
                tools.append(word_tool)
                self.logger.info("Added WordToMarkdownTool")
            except Exception as e:
                self.logger.warning(f"Could not add WordToMarkdownTool: {e}")

        # Add GoogleVoiceTool (TTS) if not present
        if "google_tts_service" not in tool_names:
            try:
                voice_tool = GoogleVoiceTool(
                    output_dir=str(self.agent_audio_dir)
                )
                tools.append(voice_tool)
                self.logger.info(f"Added GoogleVoiceTool with name: {voice_tool.name}")
            except Exception as e:
                self.logger.warning(f"Could not add GoogleVoiceTool: {e}")

        # Add ExcelTool if available and not present
        if "excel_tool" not in tool_names:
            try:
                excel_tool = ExcelTool(
                    output_dir=str(self.agent_docs_dir)
                )
                tools.append(excel_tool)
                self.logger.info("Added ExcelTool")
            except ImportError:
                self.logger.debug("ExcelTool not available")
            except Exception as e:
                self.logger.warning(f"Could not add ExcelTool: {e}")

    def _create_system_prompt(self) -> str:
        """Create the system prompt for the document agent."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Build tools list
        tools_list = ""
        for tool in self.tools:
            tools_list += f"- **{tool.name}**: {tool.description}\n"

        # Format the prompt
        system_prompt = DOCUMENT_AGENT_SYSTEM_PROMPT.format(
            name=self.name,
            today_date=now,
            tools_list=tools_list,
            format_instructions=self._format_instructions
        )

        return system_prompt

    async def configure(self, app=None) -> None:
        """
        Configure the DocumentAgent with necessary setup.

        Args:
            app: Optional aiohttp application for web integrations
        """
        await super().configure(app)
        self.logger.info(f"DocumentAgent '{self.name}' configured with {len(self.tools)} tools")

    async def load_document(self, url: str) -> Dict[str, Any]:
        """
        Load a document from a URL using WordToMarkdownTool.

        Args:
            url: URL of the Word document to load

        Returns:
            Dictionary with document content and metadata
        """
        if not url:
            return {"error": "No document URL provided", "success": False}

        # Find the Word tool
        word_tool = self.get_tool("word_to_markdown_tool")

        if not word_tool:
            return {"error": "WordToMarkdownTool not available", "success": False}

        try:
            # Use the tool to load and convert the document
            result = await word_tool._arun(url)

            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except:
                    result = {"markdown": result}

            if not result.get("success", False):
                return {
                    "error": result.get("error", "Unknown error loading document"),
                    "success": False
                }

            self._document_content = result.get("markdown", "")
            self._document_metadata = {
                "source_url": url,
                "loaded_at": datetime.now().isoformat(),
                "format": "markdown"
            }

            self.logger.info(
                f"Document loaded successfully: {len(self._document_content)} characters"
            )

            return {
                "content": self._document_content,
                "metadata": self._document_metadata,
                "success": True
            }
        except Exception as e:
            self.logger.error(f"Error loading document: {e}")
            return {"error": f"Error loading document: {str(e)}", "success": False}

    async def generate_summary(self, max_length: int = 500) -> Dict[str, Any]:
        """
        Generate a summary of the loaded document using the LLM.

        Args:
            max_length: Maximum length hint for summary (not strict)

        Returns:
            Dictionary with summary text and success status
        """
        if not self._document_content:
            self.logger.error("No document content available to summarize")
            return {"error": "No document content available to summarize", "success": False}

        content_length = len(self._document_content)
        self.logger.info(f"Generating summary for document with {content_length} characters")

        try:
            # Create summarization prompt
            prompt = f"""
Please analyze this document and create a comprehensive summary.

{self._document_content[:15000]}  # Limit to ~15k chars to avoid token issues

Your summary should:
1. Capture the main points and themes
2. Be well-structured with headers for major sections
3. Use bullet points for key details when appropriate
4. Be suitable for audio narration (clear and flowing)
5. Highlight the most important insights and conclusions

Focus on providing value and clarity in your summary.
"""

            # Use the agent's conversation method for context-aware summarization
            response = await self.invoke(
                question=prompt,
                user_id="document_processor",
                session_id=f"doc_summary_{datetime.now().timestamp()}",
                use_conversation_history=False  # Stateless for summary
            )

            if isinstance(response, AIMessage):
                summary_text = response.content
            elif isinstance(response, AgentResponse):
                summary_text = response.output
            else:
                summary_text = str(response)

            if not summary_text or len(summary_text.strip()) < 10:
                self.logger.warning("Generated summary is too short or empty")
                return {"error": "Failed to generate summary", "success": False}

            self.logger.info(f"Summary generated successfully: {len(summary_text)} characters")

            return {
                "summary": summary_text,
                "success": True
            }
        except Exception as e:
            self.logger.error(f"Error generating summary: {e}", exc_info=True)
            return {"error": f"Error generating summary: {str(e)}", "success": False}

    async def _preprocess_text_for_speech(self, text: str) -> str:
        """
        Preprocess text to make it suitable for speech synthesis.
        Removes Markdown formatting while preserving natural flow.

        Args:
            text: Text in Markdown format

        Returns:
            Clean text optimized for speech synthesis
        """
        # Remove bold/italic marks without adding explanatory text
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # Remove **bold**
        text = re.sub(r'\*(.*?)\*', r'\1', text)      # Remove *italic*
        text = re.sub(r'__(.*?)__', r'\1', text)      # Remove __bold__
        text = re.sub(r'_(.*?)_', r'\1', text)        # Remove _italic_

        # Improve lists for natural speech
        text = re.sub(r'^\s*[\*\-\+]\s+', '', text, flags=re.MULTILINE)  # Unordered lists
        text = re.sub(r'^\s*(\d+)\.\s+', '', text, flags=re.MULTILINE)   # Numbered lists

        # Convert headers maintaining original text
        text = re.sub(r'^#{1,6}\s+(.*)', r'\1', text, flags=re.MULTILINE)

        # Clean other Markdown elements
        text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)  # Links: keep only text
        text = re.sub(r'`(.*?)`', r'\1', text)           # Remove `code`
        text = re.sub(r'~~(.*?)~~', r'\1', text)         # Remove ~~strikethrough~~

        # Remove code blocks
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

        # Remove special characters
        text = re.sub(r'[|]', ' ', text)  # Remove pipes (common in tables)

        # Handle colons and bullets for better flow
        text = re.sub(r':\s*\n', '. ', text)  # Convert ":" followed by newline to period

        # Add natural pauses after paragraphs
        text = re.sub(r'\n{2,}', '. ', text)

        # Normalize spaces and punctuation
        text = re.sub(r'\s{2,}', ' ', text)      # Limit consecutive spaces
        text = re.sub(r'\.{2,}', '.', text)      # Convert multiple periods to one
        text = re.sub(r'\.\s*\.', '.', text)     # Remove double periods

        # Ensure space after punctuation
        text = re.sub(r'([.!?])\s+([A-Z])', r'\1 \2', text)

        self.logger.debug(f"Preprocessed text for speech: {len(text)} characters")

        return text.strip()

    async def generate_audio(
        self,
        text: str,
        voice_gender: str = "FEMALE",
        language_code: str = "en-US"
    ) -> Dict[str, Any]:
        """
        Generate audio narration from text using GoogleVoiceTool.

        Args:
            text: Text to convert to audio
            voice_gender: Gender of the voice (MALE or FEMALE)
            language_code: BCP-47 language code (e.g., 'en-US', 'es-ES')

        Returns:
            Dictionary with audio file information
        """
        try:
            # Find the voice tool
            voice_tool = self.get_tool("google_tts_service")

            if not voice_tool:
                self.logger.error("Google TTS tool not found")
                available_tools = [t.name for t in self.tools]
                self.logger.info(f"Available tools: {', '.join(available_tools)}")
                return {"error": "Google TTS tool not available", "success": False}

            # Preprocess text for speech
            self.logger.info("Preprocessing text for speech synthesis...")
            processed_text = await self._preprocess_text_for_speech(text)

            self.logger.info(f"Generating audio using {voice_tool.name}...")

            # Call the tool with proper parameters
            result = await voice_tool._arun(
                text=processed_text,
                voice_gender=voice_gender,
                language_code=language_code,
                file_prefix="document_summary"
            )

            # Process result
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except:
                    result = {"message": result}

            self.logger.info(f"Voice tool result: {result}")

            # Verify file exists and construct URL
            if "file_path" in result and os.path.exists(result["file_path"]):
                file_path = result["file_path"]
                # Construct URL for web access
                url = str(file_path).replace(str(self._static_path), BASE_STATIC_URL)
                result["url"] = url
                result["filename"] = os.path.basename(file_path)
                result["success"] = True
                self.logger.info(f"Audio generated successfully at: {file_path}")
                self.logger.info(f"Audio URL: {url}")
            else:
                self.logger.warning("Audio file path not found in result or file doesn't exist")
                if "file_path" in result:
                    self.logger.debug(f"Expected path: {result['file_path']}")
                result["success"] = False

            return result
        except Exception as e:
            self.logger.error(f"Error generating audio: {e}", exc_info=True)
            return {"error": f"Error generating audio: {str(e)}", "success": False}

    async def process_document_workflow(
        self,
        document_url: str,
        generate_audio_summary: bool = True
    ) -> Dict[str, Any]:
        """
        Run a complete document processing workflow:
        1. Load and convert document
        2. Generate a summary
        3. Optionally create an audio narration

        Args:
            document_url: URL to the Word document
            generate_audio_summary: Whether to generate audio narration

        Returns:
            Dictionary with document content, summary, and optional audio information
        """
        self.logger.info(f"Starting document workflow for: {document_url}")

        # Step 1: Load the document
        document_result = await self.load_document(document_url)

        if not document_result.get("success"):
            return document_result

        # Step 2: Generate summary
        try:
            summary_result = await self.generate_summary()
        except Exception as e:
            self.logger.error(f"Error generating summary: {e}")
            summary_result = {"error": str(e), "summary": "", "success": False}

        # Combine results
        workflow_result = {
            "document": {
                "content_preview": (
                    self._document_content[:500] + "..."
                    if len(self._document_content) > 500
                    else self._document_content
                ),
                "full_content_length": len(self._document_content),
                "metadata": self._document_metadata
            },
            "summary": summary_result.get("summary", ""),
            "success": summary_result.get("success", False)
        }

        # Step 3: Generate audio if requested and summary succeeded
        if generate_audio_summary and summary_result.get("success"):
            try:
                audio_result = await self.generate_audio(summary_result["summary"])
                workflow_result["audio"] = audio_result
            except Exception as e:
                self.logger.error(f"Error generating audio: {e}")
                workflow_result["audio"] = {"error": str(e), "success": False}

        return workflow_result

    def extract_filenames(self, response: Union[AIMessage, AgentResponse]) -> Dict[str, Dict[str, Any]]:
        """
        Extract filenames from agent response.

        Args:
            response: Agent response object

        Returns:
            Dictionary mapping filenames to their metadata
        """
        if isinstance(response, AIMessage):
            output = response.content
        elif isinstance(response, AgentResponse):
            output = response.output
        else:
            output = str(response)

        # Split the content by lines
        output_lines = output.splitlines()
        filenames = {}

        for line in output_lines:
            if 'filename:' in line.lower():
                filename = line.split('filename:')[1].strip()
                if filename:
                    try:
                        filename_path = Path(filename).resolve()
                        if filename_path.is_file():
                            content_type = self._mimetype_from_ext(filename_path.suffix)
                            url = str(filename_path).replace(str(self._static_path), BASE_STATIC_URL)
                            filenames[filename_path.name] = {
                                'content_type': content_type,
                                'file_path': str(filename_path),
                                'filename': filename_path.name,
                                'url': url
                            }
                    except (AttributeError, OSError):
                        pass

        return filenames

    def _mimetype_from_ext(self, ext: str) -> str:
        """Get the MIME type from file extension."""
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
        return mime_types.get(ext.lower(), 'application/octet-stream')

    async def analyze_document(
        self,
        document_url: str,
        analysis_type: str = "comprehensive"
    ) -> Dict[str, Any]:
        """
        Analyze a document with specific analysis type.

        Args:
            document_url: URL to the document
            analysis_type: Type of analysis ('comprehensive', 'summary', 'key_points', 'themes')

        Returns:
            Analysis results
        """
        # Load document if not already loaded
        if not self._document_content or self._document_metadata.get("source_url") != document_url:
            load_result = await self.load_document(document_url)
            if not load_result.get("success"):
                return load_result

        # Create analysis prompt based on type
        analysis_prompts = {
            "comprehensive": "Provide a comprehensive analysis of this document, including themes, key arguments, evidence, and conclusions.",
            "summary": "Provide a concise summary of the main points in this document.",
            "key_points": "Extract and list the key points, facts, and takeaways from this document.",
            "themes": "Identify and analyze the main themes and topics discussed in this document."
        }

        prompt = f"""{analysis_prompts.get(analysis_type, analysis_prompts['comprehensive'])}

Document Content:
{self._document_content[:10000]}
"""

        try:
            response = await self.invoke(
                question=prompt,
                user_id="document_analyzer",
                session_id=f"analysis_{datetime.now().timestamp()}",
                use_conversation_history=False
            )

            if isinstance(response, AIMessage):
                analysis = response.content
            elif isinstance(response, AgentResponse):
                analysis = response.output
            else:
                analysis = str(response)

            return {
                "analysis_type": analysis_type,
                "analysis": analysis,
                "document_metadata": self._document_metadata,
                "success": True
            }
        except Exception as e:
            self.logger.error(f"Error analyzing document: {e}", exc_info=True)
            return {"error": f"Error analyzing document: {str(e)}", "success": False}
