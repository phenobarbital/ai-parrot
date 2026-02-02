import asyncio
from parrot.bots.data import PandasAgent
from parrot.outputs import OutputMode


async def test_pandas_agent():
    data = await PandasAgent.gen_data(
        agent_name='Epson_Sales_Agent',
        query=[
            "epson_sales_data_bi",
            "epson_stores_visits_bi",
            "epson_msl_brian_bi"
        ],
    )
    agent = PandasAgent(
        name='Epson_Sales_Agent',
        model="gemini-3-pro-preview",
        local_kb=True,
        # llm='claude',
        # model='claude-sonnet-4-5',
        # llm="openai",
        # model="gpt-4o-mini",
        # sllm='groq',
        # model="moonshotai/kimi-k2-instruct-0905",
        df=data,
        max_tokens=16000
        # max_tokens=8192
    )
    await agent.configure()
#     question = """
# List all the products from epson_sales_brian_bi dataframe.
#     """
    question = """
    Top 10 store number with highest revenue in total? Provide the store numbers along with their corresponding revenue amounts.
    """
    question = """
Show total revenue by product where store designation = "Market Trainer" and return as a bar chart.
    """
#     question = """
# Which store number had the highest total revenue in July 2025? Provide the store number and the corresponding revenue amount.
#     """
#     question = """
# Show total revenue by product and store designation = "Uncovered" and return as a markdown table.
#     """
    # question = """
    # What is the total revenue of July 2025?
    # """
    async with agent:
        # response = await agent.ask(
        #     question=question,
        #     # output_mode=OutputMode.TABLE,
        #     output_mode=OutputMode.ALTAIR,
        #     format_kwargs={
        #         'html_mode': 'complete',
        #         'output_format': 'html'
        #     }
        # )
        # print(response.output, type(response.output))
        # print(':: RICH PANEL RESPONSE ::')
        # rich_print(response.response)
        # print(':: CODE GENERATED ::')
        # print(response.code)

        response = await agent.ask(
            "from epson_msl_brian_bi dataframe, find all stores in Miami, Florida and generate a folium Map",
            output_mode=OutputMode.MAP,
            format_kwargs={
                'output_format': 'html',
                'html_mode': 'complete'
            }
        )
        # print(response.output)
        # print('HTML ')
        # print(response.response)
        with open('map.html', 'w') as f:
            f.write(response.response)


if __name__ == '__main__':
    asyncio.run(test_pandas_agent())
