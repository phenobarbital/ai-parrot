import asyncio
from parrot.bots.sassie import SassieAgent

async def get_agent():
    agent = SassieAgent(
        llm='openai',
        model='gpt-4o',
        # model='gemini-2.5-pro'
    )
    await agent.configure()
    return agent

async def create_report():
    """Create a report for the agent."""
    # This method can be implemented to generate a report based on the agent's interactions or data.
    agent = await get_agent()
    async with agent:
        try:
            response, response_data = await agent.generate_report(
                prompt_file="visits_survey.txt",
                save=True,
                client='google'
            )
            if response is None:  # Error occurred
                print(f"Error generating report: {response_data.output}")
            else:
                print(f"Report generated successfully: {response_data.output}")
            final_output = response_data.output
            pdf = await agent.pdf_report(
                title='AI-Generated Sassie Survey Report',
                content=final_output,
                filename_prefix='sassie_report'
            )
            print(
                f"Report generated: {pdf}"
            )
            # -- Generate a podcast script
            podcast = await agent.speech_report(
                report=final_output,
                num_speakers=2,
                podcast_instructions='conversation.txt'
            )
            print(f"Podcast script generated: {podcast}")
        except Exception as e:
            print(f"Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(create_report())
