from __future__ import annotations
from typing import List
import textwrap
from datetime import datetime
from navconfig import BASE_DIR
from .agent import BasicAgent
from .prompts.nextstop import (
    AGENT_PROMPT,
    DEFAULT_BACKHISTORY,
    DEFAULT_CAPABILITIES
)
from ..tools import AbstractTool
from ..tools.nextstop import StoreInfo
from ..models.responses import AgentResponse


class NextStop(BasicAgent):
    """NextStop in Navigator.

        Next Stop Agent generate Visit Reports for T-ROC employees.
        based on user preferences and location data.
    """
    _agent_response = AgentResponse
    speech_context: str = (
        "The report evaluates the performance of the employee's previous visits and defines strengths and weaknesses."
    )
    speech_system_prompt: str = (
        "You are an expert brand ambassador for T-ROC, a leading retail solutions provider."
        " Your task is to create a conversational script about the strengths and weaknesses of previous visits and what"
        " factors should be addressed to achieve a perfect visit."
    )
    speech_length: int = 20  # Default length for the speech report
    num_speakers: int = 1  # Default number of speakers for the podcast

    def __init__(
        self,
        name: str = 'NextStop',
        agent_id: str = 'nextstop',
        use_llm: str = 'openai',
        llm: str = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            agent_id=agent_id,
            llm=llm,
            use_llm=use_llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            tools=tools,
            **kwargs
        )
        self.backstory = kwargs.get('backstory', DEFAULT_BACKHISTORY)
        self.capabilities = kwargs.get('capabilities', DEFAULT_CAPABILITIES)
        self.system_prompt_template = prompt_template or AGENT_PROMPT
        self._system_prompt_base = system_prompt or ''
        # Register all the tools:
        self.tools = self.default_tools(tools)

    async def report(self, prompt_file: str, **kwargs) -> AgentResponse:
        """Generate a visit report based on the provided prompt."""
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
