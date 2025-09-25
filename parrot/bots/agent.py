import textwrap
from typing import Dict, List, Tuple, Any, Optional
from abc import abstractmethod
from datetime import datetime
import aiofiles
from navconfig import BASE_DIR
from navconfig.logging import logging
from ..clients.google import GoogleGenAIClient
from .chatbot import Chatbot
from .prompts import AGENT_PROMPT
from ..tools.abstract import AbstractTool
from ..tools.pythonpandas import PythonPandasTool
from ..tools.google import GoogleLocationTool
from ..tools.openweather import OpenWeatherTool
from ..tools.gvoice import GoogleVoiceTool
from ..tools.pdfprint import PDFPrintTool
from ..tools.ppt import PowerPointTool
from ..models.google import (
    ConversationalScriptConfig,
    FictionalSpeaker
)
from ..models.responses import AIMessage, AgentResponse
from ..conf import STATIC_DIR


class BasicAgent(Chatbot):
    """Represents an Agent in Navigator.

        Agents are chatbots that can access to Tools and execute commands.
        Each Agent has a name, a role, a goal, a backstory,
        and an optional language model (llm).

        These agents are designed to interact with structured and unstructured data sources.
    """
    _agent_response = AgentResponse
    speech_context: str = ""
    speech_system_prompt: str = ""
    podcast_system_instruction: str = None
    speech_length: int = 20  # Default length for the speech report
    num_speakers: int = 1  # Default number of speakers for the podcast
    speakers: Dict[str, str] = {
        "interviewer": {
            "name": "Lydia",
            "role": "interviewer",
            "characteristic": "Bright",
            "gender": "female"
        },
        "interviewee": {
            "name": "Brian",
            "role": "interviewee",
            "characteristic": "Informative",
            "gender": "male"
        }
    }
    report_template: str = "report_template.html"

    def __init__(
        self,
        name: str = 'Agent',
        agent_id: str = 'agent',
        use_llm: str = 'google',
        llm: str = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        use_tools: bool = True,
        **kwargs
    ):
        self.agent_id = agent_id
        tools = self._get_default_tools(tools)
        super().__init__(
            name=name,
            llm=llm,
            use_llm=use_llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            tools=tools,
            use_tools=use_tools,
            **kwargs
        )
        self.system_prompt_template = prompt_template or AGENT_PROMPT
        self._system_prompt_base = system_prompt or ''
        self.enable_tools = True  # Enable tools by default
        self.operation_mode = 'agentic' # Default operation mode
        self.auto_tool_detection = True  # Enable auto tool detection by default
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Agent'
        )
        ## Google GenAI Client (for multi-modal responses and TTS generation):
        self.client = GoogleGenAIClient()
        # install agent-specific tools:
        self.tools = self.agent_tools()
        self.tool_manager.register_tools(self.tools)

    def _get_default_tools(self, tools: list) -> List[AbstractTool]:
        """Return Agent-specific tools."""
        if not tools:
            tools = []
        tools.extend(
            [
                OpenWeatherTool(default_request='weather'),
                PythonPandasTool(
                    report_dir=STATIC_DIR.joinpath(self.agent_id, 'documents')
                ),
                GoogleLocationTool(),
                GoogleVoiceTool(
                    use_long_audio_synthesis=True,
                    output_dir=STATIC_DIR.joinpath(self.agent_id, 'podcasts')
                ),
            ]
        )
        return tools

    def agent_tools(self) -> List[AbstractTool]:
        """Return the agent-specific tools."""
        return []

    def set_response(self, response: AgentResponse):
        """Set the response for the agent."""
        self._agent_response = response

    def _create_filename(self, prefix: str = 'report', extension: str = 'pdf') -> str:
        """Create a unique filename for the report."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"{prefix}_{timestamp}.{extension}"

    async def save_document(
        self,
        content: str,
        prefix: str = 'report',
        extension: str = 'txt',
        subdir: str = 'documents'
    ) -> None:
        """Save the document to a file."""
        report_filename = self._create_filename(
            prefix=prefix, extension=extension
        )
        try:
            async with aiofiles.open(
                STATIC_DIR.joinpath(self.agent_id, subdir, report_filename),
                'w'
            ) as report_file:
                await report_file.write(content)
        except Exception as e:
            self.logger.error(
                f"Failed to save document {report_filename}: {e}"
            )

    async def open_prompt(self, prompt_file: str = None) -> str:
        """
        Opens a prompt file and returns its content.
        """
        if not prompt_file:
            raise ValueError("No prompt file specified.")
        file = BASE_DIR.joinpath('prompts', self.agent_id, prompt_file)
        try:
            async with aiofiles.open(file, 'r') as f:
                content = await f.read()
            return content
        except Exception as e:
            self.logger.error(
                f"Failed to read prompt file {prompt_file}: {e}"
            )
            return None

    async def generate_report(
        self,
        prompt_file: str,
        save: bool = False,
        **kwargs
    ) -> Tuple[AIMessage, AgentResponse]:
        """Generate a report based on the provided prompt."""
        try:
            query = await self.open_prompt(prompt_file)
            query = textwrap.dedent(query)
        except (ValueError, RuntimeError) as e:
            self.logger.error(f"Error opening prompt file: {e}")
            return str(e)
        # Format the question based on keyword arguments:
        question = query.format(**kwargs)
        try:
            response = await self.invoke(
                question=question,
            )
            # Create the response object
            final_report = response.output.strip()
            if not final_report:
                raise ValueError("The generated report is empty.")
            response_data = self._agent_response(
                session_id=response.turn_id,
                data=final_report,
                agent_name=self.name,
                agent_id=self.agent_id,
                response=response,
                status="success",
                created_at=datetime.now(),
                output=response.output,
                **kwargs
            )
            # before returning, we can save the report if needed:
            if save:
                try:
                    report_filename = self._create_filename(
                        prefix='report', extension='txt'
                    )
                    async with aiofiles.open(
                        STATIC_DIR.joinpath(self.agent_id, 'documents', report_filename),
                        'w'
                    ) as report_file:
                        await report_file.write(final_report)
                    response_data.document_path = report_filename
                    self.logger.info(f"Report saved as {report_filename}")
                except Exception as e:
                    self.logger.error(f"Error saving report: {e}")
            return response, response_data
        except Exception as e:
            self.logger.error(f"Error generating report: {e}")
            return str(e)

    async def save_transcript(
        self,
        transcript: str,
        filename: str = None,
        prefix: str = 'transcript',
        subdir='transcripts'
    ) -> str:
        """Save the transcript to a file."""
        directory = STATIC_DIR.joinpath(self.agent_id, subdir)
        directory.mkdir(parents=True, exist_ok=True)
        # Create a unique filename if not provided
        if not filename:
            filename = self._create_filename(prefix=prefix, extension='txt')
        file_path = directory.joinpath(filename)
        try:
            async with aiofiles.open(file_path, 'w') as f:
                await f.write(transcript)
            self.logger.info(f"Transcript saved to {file_path}")
            return file_path
        except Exception as e:
            self.logger.error(f"Error saving transcript: {e}")
            raise RuntimeError(f"Failed to save transcript: {e}")

    async def pdf_report(
        self,
        content: str,
        filename_prefix: str = 'report',
        title: str = None,
        **kwargs
    ) -> str:
        """Generate a report based on the provided prompt."""
        # Create a unique filename for the report
        pdf_tool = PDFPrintTool(
            templates_dir=BASE_DIR.joinpath('templates'),
            output_dir=STATIC_DIR.joinpath(self.agent_id, 'documents')
        )
        result = await pdf_tool.execute(
            text=content,
            template_vars={"title": title or 'Report'},
            template_name=self.report_template,
            file_prefix=filename_prefix,

        )
        return result

    async def speech_report(
        self,
        report: str,
        max_lines: int = 15,
        num_speakers: int = 2,
        podcast_instructions: Optional[str] = 'for_podcast.txt',
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a Transcript Report and a Podcast based on findings."""
        output_directory = STATIC_DIR.joinpath(self.agent_id, 'generated_scripts')
        output_directory.mkdir(parents=True, exist_ok=True)
        script_name = self._create_filename(prefix='script', extension='txt')
        # creation of speakers:
        speakers = []
        for _, speaker in self.speakers.items():
            speaker['gender'] = speaker.get('gender', 'neutral').lower()
            speakers.append(FictionalSpeaker(**speaker))
            if len(speakers) > num_speakers:
                self.logger.warning(
                    f"Too many speakers defined, limiting to {num_speakers}."
                )
                break

        # 1. Define the script configuration
        podcast_instruction = await self.open_prompt(
            podcast_instructions or 'for_podcast.txt'
        )
        podcast_instruction.format(
            report_text=report,
        )
        script_config = ConversationalScriptConfig(
            context=self.speech_context,
            speakers=speakers,
            report_text=report,
            system_prompt=self.speech_system_prompt,
            length=self.speech_length,  # Use the speech_length attribute
            system_instruction=podcast_instruction or None
        )
        async with self.client as client:
            # 2. Generate the conversational script
            response = await client.create_conversation_script(
                report_data=script_config,
                max_lines=max_lines,  # Limit to 15 lines for brevity,
                use_structured_output=True  # Use structured output for TTS
            )
            voice_prompt = response.output
            # 3. Save the script to a File:
            script_output_path = output_directory.joinpath(script_name)
            async with aiofiles.open(script_output_path, 'w') as script_file:
                await script_file.write(voice_prompt.prompt)
            self.logger.info(f"Script saved to {script_output_path}")
        # 4. Generate the audio podcast
        output_directory = STATIC_DIR.joinpath(self.agent_id, 'podcasts')
        output_directory.mkdir(parents=True, exist_ok=True)
        async with self.client as client:
            speech_result = await client.generate_speech(
                prompt_data=voice_prompt,
                output_directory=output_directory,
            )
            if speech_result and speech_result.files:
                print(f"✅ Multi-voice speech saved to: {speech_result.files[0]}")
            # 5 Return the script and audio file paths
            return {
                'script_path': script_output_path,
                'podcast_path': speech_result.files[0] if speech_result.files else None
            }

    async def report(self, prompt_file: str, **kwargs) -> AgentResponse:
        """Generate a report based on the provided prompt."""
        query = await self.open_prompt(prompt_file)
        question = query.format(
            **kwargs
        )
        try:
            response = await self.conversation(
                question=question,
                max_tokens=8192
            )
            if isinstance(response, Exception):
                raise response
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        # Prepare the response object:
        final_report = response.output.strip()
        for key, value in kwargs.items():
            if hasattr(response, key):
                setattr(response, key, value)
        response = self._agent_response(
            user_id=str(kwargs.get('user_id', 1)),
            agent_name=self.name,
            attributes=kwargs.pop('attributes', {}),
            data=final_report,
            status="success",
            created_at=datetime.now(),
            output=response.output,
            **kwargs
        )
        return await self._generate_report(response)

    async def _generate_report(self, response: AgentResponse) -> AgentResponse:
        """Generate a report from the response data."""
        final_report = response.output.strip()
        # print(f"Final report generated: {final_report}")
        if not final_report:
            response.output = "No report generated."
            response.status = "error"
            return response
        response.transcript = final_report
        try:
            _path = await self.save_transcript(
                transcript=final_report,
            )
            response.document_path = str(_path)
            response.documents.append(response.document_path)
        except Exception as e:
            self.logger.error(f"Error generating transcript: {e}")
        # generate the PDF file:
        try:
            pdf_output = await self.pdf_report(
                content=final_report
            )
            response.pdf_path = str(pdf_output.result.get('file_path', None))
            response.documents.append(response.pdf_path)
        except Exception as e:
            self.logger.error(f"Error generating PDF: {e}")
        # generate the podcast file:
        try:
            podcast_output = await self.speech_report(
                report=final_report,
                max_lines=self.speech_length,
                num_speakers=self.num_speakers
            )
            response.podcast_path = str(podcast_output.get('podcast_path', None))
            response.script_path = str(podcast_output.get('script_path', None))
            response.documents.append(response.podcast_path)
            response.documents.append(response.script_path)
        except Exception as e:
            self.logger.error(
                f"Error generating podcast: {e}"
            )
        # Save the final report to the response
        response.output = textwrap.fill(final_report, width=80)
        response.status = "success"
        return response

    async def generate_presentation(
        self,
        content: str,
        filename_prefix: str = 'report',
        template_name: Optional[str] = None,
        pptx_template: str = "corporate_template.pptx",
        title: str = None,
        **kwargs
    ):
        """Generate a PowerPoint presentation using the provided tool."""
        tool = PowerPointTool(
            templates_dir=BASE_DIR.joinpath('templates'),
            output_dir=STATIC_DIR.joinpath(self.agent_id, 'documents')
        )
        result = await tool.execute(
            content=content,
            template_name=None,  # Explicitly disable HTML template
            template_vars=None,  # No template variables
            split_by_headings=True,  # Ensure heading-based splitting is enabled
            pptx_template=pptx_template,
            slide_layout=1,
            title_styles={
                "font_name": "Segoe UI",
                "font_size": 24,
                "bold": True,
                "font_color": "#1f497d"
            },
            content_styles={
                "font_name": "Segoe UI",
                "font_size": 14,
                "alignment": "left",
                "font_color": "#333333"
            },
            max_slides=20,
            file_prefix=filename_prefix,
        )
        return result

    async def create_speech(
        self,
        content: str,
        language: str = "en-US",
        only_script: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a Transcript Report and a Podcast based on findings."""
        output_directory = STATIC_DIR.joinpath(self.agent_id, 'documents')
        output_directory.mkdir(parents=True, exist_ok=True)
        script_name = self._create_filename(prefix='script', extension='txt')
        podcast_name = self._create_filename(prefix='podcast', extension='wav')
        try:
            async with self.client as client:
                # 1. Generate the conversational script and podcast:
                response = await client.create_speech(
                    content=content,
                    output_directory=output_directory,
                    only_script=only_script,
                    script_file=script_name,
                    podcast_file=podcast_name,
                    language=language,
                )
                return response
        except Exception as e:
            self.logger.error(
                f"Error generating speech: {e}"
            )
            raise RuntimeError(
                f"Failed to generate speech: {e}"
            )
