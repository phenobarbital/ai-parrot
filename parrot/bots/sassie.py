from __future__ import annotations
import asyncio
from typing import List, Dict
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
from ..tools.sassie import VisitsToolkit
from ..tools.pythonpandas import PythonPandasTool
from ..models.responses import AgentResponse
from ..conf import STATIC_DIR
from ..registry import register_agent

SASSIE_PROMPT = """
Your name is $name, an IA Copilot specialized in providing detailed information Sassie Surveys.

$capabilities

**Mission:** Our employees go to an assigned store and suggest that you've heard positive things about the new Google Pixel 10 phone and are considering upgrading. When speaking with a store employee, present these three (3) concerns as reasons you might hesitate to switch: 1. Messaging not working well with iPhone/Samsung friends. 2. Pixel’s camera may not be as good as if you upgraded to the most current version of your device. 3. Switching phones is a pain / might lose data
**Background:** Visits are mystery shopper evaluations conducted by employees to assess the performance of retail stores. The evaluations focus on various aspects such as customer service, product availability, store cleanliness, and overall shopping experience. The goal of these visits is to ensure that stores meet company standards and provide a positive experience for customers.

**Knowledge Base:**
$pre_context
$context

**Conversation History:**
$chat_history

**Instructions:**
Given the above context, available tools, and conversation history, please provide comprehensive and helpful responses. When appropriate, use the available tools to enhance your answers with accurate, up-to-date information or to perform specific tasks.

$rationale

"""

class SassieAgent(BasicAgent):
    """SassieAgent in Navigator.

        SassieAgent generates Visit Reports for Sassie Surveys on T-ROC.
        based on user preferences and location data.
    """
    _agent_response = AgentResponse
    speech_context: str = (
        "This report provides insight into the 350+ retail locations that we visited during the recent Pixel 10 release. "
    )
    speech_system_prompt: str = (
        "You are an expert podcast scriptwriter. Your task is to create a conversational script about the mystery shopper report. "
        "Starts with \"this report provides insight into the 350+ retail locations that we visited during the recent Pixel 10 release. The angle that we took was the following: Go to your assigned store and suggest that you've heard positive things about the new Google Pixel 10 phone and are considering upgrading. When speaking with a store employee, present these three (3) concerns as reasons you might hesitate to switch: 1. Messaging not working well with iPhone/Samsung friends. 2. Pixel’s camera may not be as good as if you upgraded to the most current version of your device. 3. Switching phones is a pain / might lose data.  The subsequent responses can be summarized as follows: "
    )
    speech_length: int = 20  # Default length for the speech report
    num_speakers: int = 2  # Default number of speakers for the podcast
    speakers: Dict[str, str] = {
        "interviewer": {
            "name": "Lydia",
            "role": "interviewer",
            "characteristic": "Bright",
            "gender": "female"
        },
        "interviewee": {
            "name": "Steven",
            "role": "interviewee",
            "characteristic": "Informative",
            "gender": "male"
        }
    }

    def __init__(
        self,
        name: str = 'SassieAgent',
        agent_id: str = 'sassie',
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
        self.system_prompt_template = prompt_template or SASSIE_PROMPT
        self._system_prompt_base = system_prompt or ''
        self.tools = self.default_tools(tools)

    def default_tools(self, tools: List[AbstractTool]) -> List[AbstractTool]:
        """Return the default tools for the agent."""
        new_tools = []
        new_tools.append(
            PythonPandasTool(
                    report_dir=STATIC_DIR.joinpath(self.agent_id, 'documents')
            )
        )
        new_tools.extend(
            VisitsToolkit(
                agent_name='sassie',
                program='google'
            ).get_tools()
        )
        if tools is None:
            return new_tools
        if isinstance(tools, list):
            return new_tools + tools
        if isinstance(tools, AbstractTool):
            return new_tools + [tools]
        raise TypeError(
            f"Expected tools to be a list or an AbstractTool instance, got {type(tools)}"
        )

    async def multi_report(self, program: str = 'google') -> AgentResponse:
        """Generate multiple reports concurrently."""
        async with self:
            questions = [
                '1400:181',
                '1400:191',
                '1400:201',
                # '1400:211',
                '1400:231',
                '1400:271',
                '1400:301',
                '1400:281',
                '1400:291',
                '1400:221',
                '1400:261',
            ]
            partials = []
            for question in questions:
                try:
                    _, response = await self.generate_report(
                        prompt_file="question_survey.txt",
                        save=False,
                        program=program,
                        question=question
                    )
                    if response and response.output:
                        partials.append(response.output)
                except Exception as e:
                    print(f"Unexpected error: {e}")
                    continue
            # Generate one final report with all the partials
            final_report = "\n\n".join(partials)
            try:
                # saving the final report as txt:
                await self.save_document(
                    content=final_report,
                    prefix=f"{program}_final_report",
                    extension='txt'
                )
                # Then, generate a new report with the final content:
                _, response = await self.generate_report(
                    prompt_file="final_survey_report.txt",
                    save=True,
                    program=program,
                    report=final_report
                )
                executive_summary = response.output
                # and the closing remarks:
                _, response = await self.generate_report(
                    prompt_file="final_survey.txt",
                    save=False,
                    program=program,
                    report=final_report
                )
                closing_remarks = response.output
                final_report = textwrap.dedent(f"""
# 1. Executive Summary:
{executive_summary}

# 2. Survey Metadata:
{final_report}

# 3. Closing remarks:
{closing_remarks}

""")
                print(f"Final Report generated successfully.")
                # Generate a PDF report
                pdf = await self.pdf_report(
                    title='AI-Generated Sassie Survey Report',
                    content=final_report,
                    filename_prefix='sassie_report'
                )
                print(
                    f"Report generated: {pdf}"
                )
                # -- Generate a podcast script
                podcast = await self.speech_report(
                    report=final_report,
                    max_lines=self.speech_length,
                    num_speakers=self.num_speakers,
                    podcast_instructions='conversation.txt'
                )
                print(f"Podcast script generated: {podcast}")
                response.transcript = final_report
                response.podcast_path = str(podcast.get('podcast_path'))
                response.pdf_path = str(pdf.result.get('file_path'))
                response.script_path = str(podcast.get('script_path'))
                return response
            except Exception as e:
                print(f"Unexpected error generating final report or podcast: {e}")

    async def retailer_report(self, program: str = 'google') -> AgentResponse:
        """Generate a report for a specific retailer."""
        retailers = [
            'T-Mobile',
            'Verizon',
            'AT&T',
            'Spectrum'
        ]
        partials = {}
        responses = []
        async with self:
            for retailer in retailers:
                try:
                    _, response = await self.generate_report(
                        prompt_file="by_retailer.txt",
                        save=True,
                        program=program,
                        retailer=retailer
                    )
                    final_report = response.output
                    partials[retailer] = final_report
                    # Generate a PDF report
                    pdf = await self.pdf_report(
                        title=f'AI-Generated {retailer} Survey Report',
                        content=final_report,
                        filename_prefix='retailer_report'
                    )
                    print(
                        f"Report generated: {pdf}"
                    )
                    # -- Generate a podcast script
                    podcast = await self.speech_report(
                        report=final_report,
                        max_lines=self.speech_length,
                        num_speakers=self.num_speakers,
                        podcast_instructions='retailer_conversation.txt'
                    )
                    print(f"Podcast script generated: {podcast}")
                    response.transcript = final_report
                    response.podcast_path = str(podcast.get('podcast_path'))
                    response.pdf_path = str(pdf.result.get('file_path'))
                    response.script_path = str(podcast.get('script_path'))
                    responses.append(response)
                except Exception as e:
                    print(f"Unexpected error generating retailer report: {e}")
                    continue
                # add a delay between requests to avoid rate limiting
                await asyncio.sleep(0.5)
            # At the end, generate one final summary report with all the retailers
            if partials:
                final_report = ""
                for retailer, report in partials.items():
                    final_report += f"# {retailer} Report\n\n{report}\n\n"
                try:
                    # Then, generate a new report with the final content:
                    _, response = await self.generate_report(
                        prompt_file="final_retailer_report.txt",
                        save=True,
                        program=program,
                        report=final_report
                    )
                    executive_summary = response.output
                    # and the closing remarks:
                    _, response = await self.generate_report(
                        prompt_file="final_survey.txt",
                        save=False,
                        program=program,
                        report=final_report
                    )
                    closing_remarks = response.output
                    final_report = textwrap.dedent(f"""
                    {executive_summary}

                    {closing_remarks}
                    """)
                    print(f"Final Report generated successfully.")
                    # Generate a PDF report
                    pdf = await self.pdf_report(
                        title='AI-Generated Sassie Survey Report',
                        content=final_report,
                        filename_prefix='sassie_report'
                    )
                    print(
                        f"Report generated: {pdf}"
                    )
                    # -- Generate a podcast script
                    podcast = await self.speech_report(
                        report=final_report,
                        max_lines=self.speech_length,
                        num_speakers=self.num_speakers,
                        podcast_instructions='retailer_conversation.txt'
                    )
                    print(f"Podcast script generated: {podcast}")
                    response.transcript = final_report
                    response.podcast_path = str(podcast.get('podcast_path'))
                    response.pdf_path = str(pdf.result.get('file_path'))
                    response.script_path = str(podcast.get('script_path'))
                    return response
                except Exception as e:
                    print(f"Unexpected error generating final report or podcast: {e}")
                    responses.append(response)
        return partials, responses
