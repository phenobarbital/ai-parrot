import asyncio
from parrot.bots.nextstop import NextStop

async def test_nextstop():
    bot = NextStop(
        llm='openai',
        model='gpt-4o',
    )
    await bot.configure()
    return bot

# Function to debug and clean tool schemas
def debug_and_clean_schemas(agent):
    """Debug and show which schemas are problematic."""
    if not hasattr(agent._llm, 'tools'):
        print("No tools found")
        return

    problematic_tools = []

    for tool_name, tool in agent._llm.tools.items():
        try:
            schema = tool.get_tool_schema()
            schema_str = str(schema)

            # Check for problematic fields
            issues = []
            if 'additionalProperties' in schema_str:
                issues.append('additionalProperties')
            if 'anyOf' in schema_str:
                issues.append('anyOf')
            if 'prefixItems' in schema_str:
                issues.append('prefixItems')

            if issues:
                print(f"❌ Tool {tool_name} has issues: {', '.join(issues)}")
                problematic_tools.append(tool_name)
            else:
                print(f"✅ Tool {tool_name} looks clean")

        except Exception as e:
            print(f"❌ Error with tool {tool_name}: {e}")
            problematic_tools.append(tool_name)

    return problematic_tools

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    bot = loop.run_until_complete(test_nextstop())
    print("NextStop bot configured:", bot)

    # Debug the schemas
    # problematic_tools = debug_and_clean_schemas(bot)
    # print(f"\nProblematic tools: {problematic_tools}")

    response, response_data = loop.run_until_complete(
        bot.generate_report(
            "for_store.txt", store_id="BBY1220",
            save=True,  # Save the report
        )
    )
    final_report = response_data.data
    # Print the final report
    loop.run_until_complete(
        bot.pdf_report(final_report)
    )
    # Generate the speech Report:
    loop.run_until_complete(
        bot.speech_report(final_report, max_lines=20)
    )
    print("Final Report Generated Successfully")
    loop.close()
