import asyncio
from parrot.bots.data import PandasAgent
from parrot.outputs import OutputMode


async def test_pandas_agent():
    data = await PandasAgent.gen_data(
        agent_name='Epson_Sales_Agent',
        query=["epson_sales_brian_bi", "Epson_Visit_Hours"]
    )
    agent = PandasAgent(
        name='Epson_Sales_Agent',
        # llm='openai',
        # model='gpt-4.1',
        df=data,
        max_tokens=16000
    )
    await agent.configure()
#     question = """
# List all the products from epson_sales_brian_bi dataframe.
#     """
    # question = """
    # Top 10 store number with highest revenue in total? Provide the store numbers along with their corresponding revenue amounts.
    # """
#     question = """
# Show total revenue by product where store designation = "Market Trainer" and return as a markdown table.
#     """
    question = """
Which store number had the highest total revenue in July 2025? Provide the store number and the corresponding revenue amount.
    """
#     question = """
# Show total revenue by product and store designation = "Uncovered" and return as a markdown table.
#     """
    # question = """
    # What is the total revenue of July 2025?
    # """
    async with agent:
        response = await agent.ask(question)
        print(response.output)

        # response = await agent.ask(
        #     "Show total revenue by product where store designation = \"Market Trainer\" and return as a bar chart.",
        #     output_mode=OutputMode.PLOTLY,
        #     format_kwargs={
        #         'export_format': 'both',
        #         'return_code': True,
        #         'html_mode': 'complete'
        #     }
        # )
        # print(response.output)
        # print('HTML ')
        # print(response.response)


if __name__ == '__main__':
    asyncio.run(test_pandas_agent())
