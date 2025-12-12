"""
Example: Redis Persistence for AgentsCrew

This example demonstrates how to:
1. Create a CrewDefinition with multiple agents
2. Save it to Redis using the key format 'crew:{name}'
3. Load it back from Redis
4. Update metadata
5. Delete the crew

The CrewRedis class provides async-based persistence for crew definitions,
allowing crews to be stored, retrieved, and managed across sessions.
"""
import asyncio
from datetime import datetime
from parrot.handlers.crew.models import (
    CrewDefinition,
    AgentDefinition,
    FlowRelation,
    ExecutionMode
)
from parrot.handlers.crew.redis_persistence import CrewRedis


async def example_basic_persistence():
    """Basic example: Save and load a crew definition."""
    print("=" * 60)
    print("Example 1: Basic Persistence")
    print("=" * 60)

    # Initialize Redis persistence
    crew_redis = CrewRedis()

    # Check connection
    if not await crew_redis.ping():
        print("❌ Redis connection failed!")
        return

    print("✓ Connected to Redis\n")

    # Create a crew definition
    crew_def = CrewDefinition(
        name="blog_writing_team",
        description="A crew for researching and writing blog posts",
        execution_mode=ExecutionMode.SEQUENTIAL,
        agents=[
            AgentDefinition(
                agent_id="researcher",
                agent_class="BasicAgent",
                name="Content Researcher",
                config={
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "max_tokens": 2000
                },
                tools=["web_search", "summarize", "extract_facts"],
                system_prompt="You are an expert researcher who gathers comprehensive information on topics."
            ),
            AgentDefinition(
                agent_id="writer",
                agent_class="BasicAgent",
                name="Blog Writer",
                config={
                    "model": "gpt-4",
                    "temperature": 0.9,
                    "max_tokens": 3000
                },
                tools=["write", "format_markdown"],
                system_prompt="You are a creative blog writer who creates engaging content."
            ),
            AgentDefinition(
                agent_id="editor",
                agent_class="BasicAgent",
                name="Editor",
                config={
                    "model": "gpt-4",
                    "temperature": 0.5,
                    "max_tokens": 2000
                },
                tools=["grammar_check", "style_check"],
                system_prompt="You are an editor who ensures clarity, grammar, and style."
            )
        ],
        shared_tools=["calculator", "fact_checker"],
        metadata={
            "version": "1.0",
            "author": "content_team",
            "category": "content_creation"
        }
    )

    print(f"Created crew: {crew_def.name}")
    print(f"  - Crew ID: {crew_def.crew_id}")
    print(f"  - Agents: {len(crew_def.agents)}")
    print(f"  - Execution mode: {crew_def.execution_mode.value}\n")

    # Save to Redis
    print("Saving crew to Redis...")
    saved = await crew_redis.save_crew(crew_def)
    if saved:
        print(f"✓ Crew saved with key: crew:{crew_def.name}\n")
    else:
        print("❌ Failed to save crew\n")
        return

    # Load from Redis by name
    print("Loading crew from Redis by name...")
    loaded_crew = await crew_redis.load_crew("blog_writing_team")
    if loaded_crew:
        print(f"✓ Loaded crew: {loaded_crew.name}")
        print(f"  - Agents loaded: {len(loaded_crew.agents)}")
        print(f"  - First agent: {loaded_crew.agents[0].name}")
        print(f"  - Second agent: {loaded_crew.agents[1].name}")
        print(f"  - Third agent: {loaded_crew.agents[2].name}\n")
    else:
        print("❌ Failed to load crew\n")

    # Load from Redis by ID
    print("Loading crew from Redis by ID...")
    loaded_by_id = await crew_redis.load_crew_by_id(crew_def.crew_id)
    if loaded_by_id:
        print(f"✓ Loaded crew by ID: {loaded_by_id.name}\n")
    else:
        print("❌ Failed to load crew by ID\n")

    # List all crews
    print("Listing all crews...")
    all_crews = await crew_redis.list_crews()
    print(f"Available crews: {all_crews}\n")

    # Cleanup
    print("Cleaning up...")
    deleted = await crew_redis.delete_crew("blog_writing_team")
    if deleted:
        print("✓ Crew deleted\n")

    await crew_redis.close()


async def example_flow_mode_crew():
    """Example: Create and persist a flow-based crew with dependencies."""
    print("=" * 60)
    print("Example 2: Flow-Based Crew with Dependencies")
    print("=" * 60)

    crew_redis = CrewRedis()

    if not await crew_redis.ping():
        print("❌ Redis connection failed!")
        return

    print("✓ Connected to Redis\n")

    # Create a flow-based crew with dependencies
    crew_def = CrewDefinition(
        name="research_synthesis_team",
        description="A crew that performs parallel research and synthesizes results",
        execution_mode=ExecutionMode.FLOW,
        agents=[
            AgentDefinition(
                agent_id="coordinator",
                agent_class="BasicAgent",
                name="Research Coordinator",
                config={"model": "gpt-4", "temperature": 0.7},
                tools=["task_decomposition"],
                system_prompt="You coordinate research tasks and decompose topics."
            ),
            AgentDefinition(
                agent_id="tech_researcher",
                agent_class="BasicAgent",
                name="Tech Researcher",
                config={"model": "gpt-4", "temperature": 0.7},
                tools=["web_search", "arxiv_search"],
                system_prompt="You research technical topics."
            ),
            AgentDefinition(
                agent_id="market_researcher",
                agent_class="BasicAgent",
                name="Market Researcher",
                config={"model": "gpt-4", "temperature": 0.7},
                tools=["web_search", "data_analysis"],
                system_prompt="You research market trends and business aspects."
            ),
            AgentDefinition(
                agent_id="synthesizer",
                agent_class="BasicAgent",
                name="Synthesizer",
                config={"model": "gpt-4", "temperature": 0.8},
                tools=["summarize", "combine_insights"],
                system_prompt="You synthesize research from multiple sources into coherent insights."
            )
        ],
        flow_relations=[
            # Coordinator must complete first
            FlowRelation(source="coordinator", target=["tech_researcher", "market_researcher"]),
            # Both researchers must complete before synthesizer
            FlowRelation(source=["tech_researcher", "market_researcher"], target="synthesizer")
        ],
        shared_tools=["calculator", "citation_formatter"],
        metadata={
            "version": "1.0",
            "author": "research_team",
            "category": "research",
            "parallel_agents": ["tech_researcher", "market_researcher"]
        }
    )

    print(f"Created flow-based crew: {crew_def.name}")
    print(f"  - Execution mode: {crew_def.execution_mode.value}")
    print(f"  - Flow relations: {len(crew_def.flow_relations)}")
    print(f"  - Parallel execution enabled for tech and market researchers\n")

    # Save to Redis
    saved = await crew_redis.save_crew(crew_def)
    if saved:
        print(f"✓ Crew saved with key: crew:{crew_def.name}\n")

        # Get metadata
        metadata = await crew_redis.get_crew_metadata("research_synthesis_team")
        if metadata:
            print("Crew metadata:")
            for key, value in metadata.items():
                print(f"  - {key}: {value}")
            print()

    # Cleanup
    await crew_redis.delete_crew("research_synthesis_team")
    await crew_redis.close()


async def example_metadata_update():
    """Example: Update crew metadata without reloading full definition."""
    print("=" * 60)
    print("Example 3: Metadata Updates")
    print("=" * 60)

    crew_redis = CrewRedis()

    if not await crew_redis.ping():
        print("❌ Redis connection failed!")
        return

    print("✓ Connected to Redis\n")

    # Create a simple crew
    crew_def = CrewDefinition(
        name="simple_crew",
        description="A simple crew for testing metadata updates",
        execution_mode=ExecutionMode.SEQUENTIAL,
        agents=[
            AgentDefinition(
                agent_id="agent1",
                agent_class="BasicAgent",
                name="Agent 1",
                config={"model": "gpt-4"},
                tools=["search"]
            )
        ],
        metadata={
            "status": "draft",
            "version": "0.1",
            "runs": 0
        }
    )

    # Save
    await crew_redis.save_crew(crew_def)
    print(f"Created crew with metadata: {crew_def.metadata}\n")

    # Simulate usage: update metadata
    print("Simulating crew usage: updating metadata...")
    updated = await crew_redis.update_crew_metadata(
        "simple_crew",
        {
            "status": "active",
            "version": "1.0",
            "runs": 5,
            "last_run": datetime.utcnow().isoformat()
        }
    )

    if updated:
        print("✓ Metadata updated\n")

        # Load and verify
        crew = await crew_redis.load_crew("simple_crew")
        if crew:
            print("Updated metadata:")
            for key, value in crew.metadata.items():
                print(f"  - {key}: {value}")
            print()

    # Cleanup
    await crew_redis.delete_crew("simple_crew")
    await crew_redis.close()


async def example_list_and_manage():
    """Example: List and manage multiple crews."""
    print("=" * 60)
    print("Example 4: List and Manage Multiple Crews")
    print("=" * 60)

    crew_redis = CrewRedis()

    if not await crew_redis.ping():
        print("❌ Redis connection failed!")
        return

    print("✓ Connected to Redis\n")

    # Create multiple crews
    crews_to_create = [
        ("content_crew", "Content creation team", ExecutionMode.SEQUENTIAL),
        ("research_crew", "Research team", ExecutionMode.PARALLEL),
        ("analysis_crew", "Data analysis team", ExecutionMode.FLOW)
    ]

    print("Creating multiple crews...")
    for name, description, mode in crews_to_create:
        crew = CrewDefinition(
            name=name,
            description=description,
            execution_mode=mode,
            agents=[
                AgentDefinition(
                    agent_id=f"{name}_agent",
                    agent_class="BasicAgent",
                    name=f"{name.capitalize()} Agent",
                    config={"model": "gpt-4"}
                )
            ]
        )
        await crew_redis.save_crew(crew)
        print(f"  ✓ Created: {name}")

    print()

    # List all crews
    print("All crews in Redis:")
    crew_names = await crew_redis.list_crews()
    for name in crew_names:
        exists = await crew_redis.crew_exists(name)
        print(f"  - {name} (exists: {exists})")

    print()

    # Get all crew definitions
    print("Loading all crew definitions...")
    all_crews = await crew_redis.get_all_crews()
    print(f"Total crews loaded: {len(all_crews)}")
    for crew in all_crews:
        print(f"  - {crew.name}: {crew.description} ({crew.execution_mode.value})")

    print()

    # Cleanup all
    print("Cleaning up...")
    for name in crew_names:
        await crew_redis.delete_crew(name)
        print(f"  ✓ Deleted: {name}")

    await crew_redis.close()


async def main():
    """Run all examples."""
    try:
        await example_basic_persistence()
        print("\n" + "=" * 60 + "\n")

        await example_flow_mode_crew()
        print("\n" + "=" * 60 + "\n")

        await example_metadata_update()
        print("\n" + "=" * 60 + "\n")

        await example_list_and_manage()

        print("\n✓ All examples completed successfully!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
