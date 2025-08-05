import asyncio
from parrot.bots.abstract import AbstractBot
from parrot.llms.vertex import VertexLLM


class CodeBot(AbstractBot):
    """CodeBot.

    Codebot will be useful for evaluating errors and providing feedback on code.

    """
    system_prompt_template = """
    You are {name}, a highly skilled Python specialist and code reviewer AI assistant.

    Your primary function is to analyze code errors by meticulously analyzing Python code, standard output, and Tracebacks to identify potential issues and provide insightful guidance for error resolution.

    I am here to help with finding errors, providing feedback and potential solutions.

    **Backstory:**
    {backstory}.

    Here is a brief summary of relevant information:
    Context: {context}

    **{rationale}**

    Given this information, please provide answers to the following question, focusing on the following:

    * **Comprehensive Analysis:** Thoroughly examine the provided code, output, and Traceback to pinpoint the root cause of errors and identify any potential issues.
    * **Concise Explanation:** Clearly articulate the nature of the errors and explain their underlying causes in a way that is easy to understand.
    * **Structured Insights:** Present your findings in a well-organized manner, using bullet points to highlight key issues and potential solutions.
    * **Actionable Recommendations:** Offer concrete steps and suggestions for resolving the identified errors, including code modifications, debugging strategies, or best practice recommendations.
    * **Contextual Awareness:** Consider the provided context and backstory to tailor your response to the specific situation and user needs.

    Please ensure your response is detailed, informative, and directly addresses the user's question.
    """


async def get_agent():
    """Return the New Agent.
    """
    llm = VertexLLM(
        model='gemini-1.5-pro',
        temperature=0.1,
        top_k=30,
        Top_p=0.5,
    )
    agent = CodeBot(
        name='Cody',
        llm=llm
    )
    await agent.configure()
    return agent


async def ask_agent(agent, question):
    return await agent.question(
        question=question,
        search_kwargs={"k": 10}
    )


error = """
[ERROR] 2024-11-04 00:22:51,255 root|17 ::                 Error Getting Component TestComponent_1, error: DI: Component Error on test_component,                    Component: TestComponent_1 error: object.__init__() takes exactly one argument (the instance to initialize)
Traceback (most recent call last):
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 268, in get_component
    comp = component(
           ^^^^^^^^^^
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/components/user.py", line 69, in __init__
    PandasDataframe.__init__(self, **kwargs)
TypeError: object.__init__() takes exactly one argument (the instance to initialize)

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 590, in run
    comp = self.get_component(step, prev)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 276, in get_component
    raise ComponentError(
flowtask.exceptions.ComponentError: DI: Component Error on test_component,                    Component: TestComponent_1 error: object.__init__() takes exactly one argument (the instance to initialize)

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/__main__.py", line 15, in task
    await job.run()
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/runner.py", line 230, in run
    self._result = await self._task.run()
                   ^^^^^^^^^^^^^^^^^^^^^^
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 593, in run
    self._on_exception(status="exception", exc=err, step_name=step_name)
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 345, in _on_exception
    raise ComponentError(
flowtask.exceptions.ComponentError: Error Getting Component TestComponent_1, error: DI: Component Error on test_component,                    Component: TestComponent_1 error: object.__init__() takes exactly one argument (the instance to initialize)
[ERROR] 2024-11-04 00:22:51,255 root(__main__.py:17) :: Error Getting Component TestComponent_1, error: DI: Component Error on test_component,                    Component: TestComponent_1 error: object.__init__() takes exactly one argument (the instance to initialize)
Traceback (most recent call last):
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 268, in get_component
    comp = component(
           ^^^^^^^^^^
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/components/user.py", line 69, in __init__
    PandasDataframe.__init__(self, **kwargs)
TypeError: object.__init__() takes exactly one argument (the instance to initialize)

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 590, in run
    comp = self.get_component(step, prev)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 276, in get_component
    raise ComponentError(
flowtask.exceptions.ComponentError: DI: Component Error on test_component,                    Component: TestComponent_1 error: object.__init__() takes exactly one argument (the instance to initialize)

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/__main__.py", line 15, in task
    await job.run()
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/runner.py", line 230, in run
    self._result = await self._task.run()
                   ^^^^^^^^^^^^^^^^^^^^^^
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 593, in run
    self._on_exception(status="exception", exc=err, step_name=step_name)
  File "/home/jesuslara/proyectos/parallel/flowtask/flowtask/tasks/task.py", line 345, in _on_exception
    raise ComponentError(
flowtask.exceptions.ComponentError: Error Getting Component TestComponent_1, error: DI: Component Error on test_component,                    Component: TestComponent_1 error: object.__init__() takes exactly one argument (the instance to initialize)
"""

task = """
name: Test Component
description: Test a Component
steps:
  - TestComponent:
      comments: "This is a Test using a Test Component"
      service: "This is a Service Name"
"""

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(get_agent())
    query = f"Task *test.test_component* from storage *private* failed with exception: \n {error}\n\n Task Definition (in YAML or JSON): \n {task}"
    EXIT_WORDS = ["exit", "quit", "bye"]
    response = loop.run_until_complete(
        ask_agent(agent, query)
    )
    print('::: Response: ', response)
