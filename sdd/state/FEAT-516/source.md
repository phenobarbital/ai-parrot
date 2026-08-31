# Inline Source

dev_loop and dev_flow node caching: `packages/ai-parrot/src/parrot/flows/dev_flow/` is an AgentsFlow workflow following our Spec-Driven Development procedure (proactive Spec-Driven Development), we need to add Node caching: each node in the flow should cache its operation, so if this flow is executed again, not ALL steps are performed, but steps are retrieved from the cache (example: retrieving the research from a node cache in Redis or allowing the Development Node to understand what task the code was in in the worktree), the "bug intake", "research" and "development" nodes need to catch the work to be re-used if for some reason the flow stops by any exception, if a job is restarted, flow is recovered from node caching

