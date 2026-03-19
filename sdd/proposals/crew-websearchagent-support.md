# Support WebSearchAgent in CrewBuilder UI and CrewBuilder handler.

WebSearchAgent is a new type of Agent supporting directly LLMs calls to do synthesis or doing a "contrastive search"

```
# Normal search (unchanged behavior)
agent = WebSearchAgent()

# Two-step contrastive search (competitors/alternatives analysis)
agent = WebSearchAgent(contrastive_search=True)

# With synthesis step (LLM analyzes results, no tools)
agent = WebSearchAgent(synthesize=True)

# All three steps: search → contrastive → synthesis
agent = WebSearchAgent(contrastive_search=True, synthesize=True)

# Custom prompts (use $query and $search_results placeholders)
agent = WebSearchAgent(
    contrastive_search=True,
    contrastive_prompt="Compare $query vs: $search_results",
    synthesize=True,
    synthesize_prompt="Summarize for $query: $search_results",
)

```

## Changes on CrewBuilder UI (navigator-frontend-next repository)

- on svelteflow UI designer: if a WebSearchAgent is added, when clicked, in configuration of Agent we need to add:
 * temperature default to zero (avoid hallucination)
 * a checkbox for enabling the contrastive_search (then, enable a textare for adding the prompt)
 * a checkbox for enabling synthetize (then, enable a textare for adding the prompt)

## Changes on CrewHandler (ai-parrot repository, at parrot/handlers/crew/handler.py)

- check if contrastive_search and synthetize parameters are correctly passed to each agent and saved into the JSON definition.