import textwrap
from typing import Dict, List, Tuple, Any
from datetime import datetime
import aiofiles
from navconfig import BASE_DIR
from navconfig.logging import logging
from ..clients.google import GoogleGenAIClient
from .chatbot import Chatbot
from .prompts import AGENT_PROMPT
from ..tools.abstract import AbstractTool
from ..tools.pythonpandas import PythonPandasTool
from ..tools.google import GoogleLocationTool, GoogleRoutesTool
from ..tools.openweather import OpenWeatherTool
from ..tools.excel import ExcelTool
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
    speech_length: int = 10  # Default length for the speech report
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
        **kwargs
    ):
        super().__init__(
            name=name,
            llm=llm,
            use_llm=use_llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            tools=tools,
            **kwargs
        )
        self.agent_id = agent_id
        self.system_prompt_template = prompt_template or AGENT_PROMPT
        self._system_prompt_base = system_prompt or ''
        self.enable_tools = True  # Enable tools by default
        self.auto_tool_detection = True  # Enable auto tool detection by default
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Agent'
        )
        ## Google GenAI Client:
        self.client = GoogleGenAIClient()

    def default_tools(self, tools: List[AbstractTool]) -> List[AbstractTool]:
        """Return the default tools for the agent."""
        if not tools:
            tools = []
        tools.extend(
            [
                OpenWeatherTool(default_request='weather'),
                PythonPandasTool(
                    report_dir=STATIC_DIR.joinpath(self.name, 'documents')
                ),
                GoogleLocationTool(),
                GoogleRoutesTool(
                    output_dir=STATIC_DIR.joinpath(self.name, 'routes')
                ),
                ExcelTool(
                    output_dir=STATIC_DIR.joinpath(self.name, 'documents')
                ),
                GoogleVoiceTool(
                    use_long_audio_synthesis=True,
                    output_dir=STATIC_DIR.joinpath(self.name, 'podcasts')
                ),
                PDFPrintTool(
                    output_dir=STATIC_DIR.joinpath(self.name, 'documents')
                ),
                PowerPointTool(
                    output_dir=STATIC_DIR.joinpath(self.name, 'presentations')
                )
            ]
        )
        return tools

    def set_response(self, response: AgentResponse):
        """Set the response for the agent."""
        self._agent_response = response

    def _create_filename(self, prefix: str = 'report', extension: str = 'pdf') -> str:
        """Create a unique filename for the report."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"{prefix}_{timestamp}.{extension}"

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
            raise RuntimeError(
                f"Failed to read prompt file {prompt_file}: {e}"
            )

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
                        BASE_DIR.joinpath('static', self.name, 'documents', report_filename),
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

    async def pdf_report(self, prompt: str, **kwargs) -> str:
        """Generate a report based on the provided prompt."""
        # Create a unique filename for the report
        pdf_tool = PDFPrintTool(
            templates_dir=BASE_DIR.joinpath('templates'),
            output_dir=BASE_DIR.joinpath('static', self.name, 'documents')
        )
        result = await pdf_tool.execute(
            text=prompt,
            template_name="report_template.html",
            file_prefix="nextstop_report",
        )
        return result

    async def speech_report(self, report: str, max_lines: int = 15, **kwargs) -> Dict[str, Any]:
        """Generate a PDF Report and a Podcast based on findings."""
        output_directory = BASE_DIR.joinpath('static', self.name, 'generated_scripts')
        output_directory.mkdir(parents=True, exist_ok=True)
        script_name = self._create_filename(prefix='script', extension='txt')
        # creation of speakers:
        speakers = []
        for _, speaker in self.speakers.items():
            speaker['gender'] = speaker.get('gender', 'neutral').lower()
            speakers.append(FictionalSpeaker(**speaker))
        # 1. Define the script configuration
        script_config = ConversationalScriptConfig(
            context=self.speech_context,
            speakers=speakers,
            report_text=report,
            system_prompt=self.speech_system_prompt,
            length=self.speech_length,  # Use the speech_length attribute
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
