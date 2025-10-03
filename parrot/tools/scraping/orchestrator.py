"""
ScrapingOrchestrator for AI-Parrot
Complete integration layer that coordinates LLM-directed web scraping
"""
from typing import Dict, List, Any, Optional, Union, Callable
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from ...bots.scraper import ScrapingAgent
from .tool import WebScrapingTool
from .models import ScrapingStep, ScrapingSelector, ScrapingResult
from ...stores.kb import KnowledgeBaseStore
from ...loaders.text import TextLoader
from ...models.responses import AgentResponse


class ScrapingOrchestrator:
    """
    High-level orchestrator that manages the complete LLM-directed scraping workflow.

    This class integrates with AI-parrot's existing infrastructure:
    - Uses the knowledge base system for storing scraped content
    - Integrates with the loader system for content processing
    - Supports agent orchestration patterns
    - Provides hooks for custom post-processing
    """

    def __init__(
        self,
        agent_name: str = "WebScrapingAgent",
        driver_type: str = 'selenium',
        knowledge_base: Optional[KnowledgeBaseStore] = None,
        **kwargs
    ):
        self.logger = logging.getLogger("AI-Parrot.ScrapingOrchestrator")

        # Initialize the scraping agent
        self.scraping_agent = ScrapingAgent(
            name=agent_name,
            driver_type=driver_type,
            **kwargs
        )

        # Knowledge base integration
        self.knowledge_base = knowledge_base
        self.auto_store_results = kwargs.get('auto_store_results', True)

        # Result processing
        self.post_processors: List[Callable] = []
        self.result_filters: List[Callable] = []

        # Configuration
        self.max_concurrent_scrapes = kwargs.get('max_concurrent_scrapes', 3)
        self.retry_failed_scrapes = kwargs.get('retry_failed_scrapes', True)
        self.respect_robots_txt = kwargs.get('respect_robots_txt', True)

        # Statistics tracking
        self.session_stats = {
            'total_requests': 0,
            'successful_scrapes': 0,
            'failed_scrapes': 0,
            'pages_processed': 0,
            'start_time': datetime.now()
        }

    async def execute_scraping_mission(
        self,
        mission_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a complete scraping mission with multiple targets and objectives.

        Args:
            mission_config: Configuration dictionary containing:
                - targets: List of URLs or site configurations
                - objectives: What to extract from each target
                - authentication: Login credentials if needed
                - output_config: How to store/process results
                - constraints: Rate limiting, ethics, etc.

        Returns:
            Dictionary with complete mission results and statistics
        """
        self.logger.info(f"Starting scraping mission with {len(mission_config.get('targets', []))} targets")

        mission_results = {
            'mission_id': mission_config.get('mission_id', f"mission_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
            'start_time': datetime.now().isoformat(),
            'targets': [],
            'statistics': {},
            'errors': []
        }

        try:
            targets = mission_config.get('targets', [])

            # Process targets concurrently with semaphore control
            semaphore = asyncio.Semaphore(self.max_concurrent_scrapes)
            tasks = []

            for i, target in enumerate(targets):
                task = self._process_single_target(semaphore, target, mission_config, i)
                tasks.append(task)

            # Execute all scraping tasks
            target_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(target_results):
                if isinstance(result, Exception):
                    self.logger.error(f"Target {i} failed: {str(result)}")
                    mission_results['errors'].append({
                        'target_index': i,
                        'error': str(result),
                        'target_config': targets[i] if i < len(targets) else 'unknown'
                    })
                else:
                    mission_results['targets'].append(result)

            # Calculate statistics
            mission_results['statistics'] = self._calculate_mission_statistics(mission_results)

            # Store results if configured
            if self.auto_store_results and self.knowledge_base:
                await self._store_mission_results(mission_results)

        except Exception as e:
            self.logger.error(f"Mission execution failed: {str(e)}")
            mission_results['errors'].append({
                'type': 'mission_failure',
                'error': str(e)
            })

        finally:
            mission_results['end_time'] = datetime.now().isoformat()
            mission_results['duration'] = (
                datetime.fromisoformat(mission_results['end_time']) -
                datetime.fromisoformat(mission_results['start_time'])
            ).total_seconds()

        return mission_results

    async def _process_single_target(
        self,
        semaphore: asyncio.Semaphore,
        target_config: Dict[str, Any],
        mission_config: Dict[str, Any],
        target_index: int
    ) -> Dict[str, Any]:
        """Process a single scraping target with concurrency control"""
        async with semaphore:
            self.session_stats['total_requests'] += 1

            # Build complete request for this target
            request = {
                'target_url': target_config.get('url') or target_config.get('target_url'),
                'objective': target_config.get('objective') or mission_config.get('default_objective'),
                'authentication': target_config.get('authentication') or mission_config.get('authentication'),
                'constraints': mission_config.get('constraints', {}),
                'base_url': target_config.get('base_url', ''),
                'custom_selectors': target_config.get('selectors', []),
                'custom_steps': target_config.get('steps', [])
            }

            # Check if we have prior knowledge about this site
            recommendations = await self.scraping_agent.get_site_recommendations(request['target_url'])

            # Execute the intelligent scraping
            scraping_results = await self.scraping_agent.execute_intelligent_scraping(request)

            # Process results through filters and post-processors
            processed_results = await self._process_results(scraping_results, target_config)

            # Update statistics
            if processed_results:
                successful_results = [r for r in processed_results if r.success]
                self.session_stats['successful_scrapes'] += len(successful_results)
                self.session_stats['failed_scrapes'] += len(processed_results) - len(successful_results)
                self.session_stats['pages_processed'] += len(processed_results)

            return {
                'target_index': target_index,
                'target_config': target_config,
                'request': request,
                'recommendations': recommendations,
                'scraping_results': [
                    {
                        'url': r.url,
                        'success': r.success,
                        'extracted_data': r.extracted_data,
                        'metadata': r.metadata,
                        'error_message': r.error_message
                    } for r in processed_results
                ],
                'processed_at': datetime.now().isoformat()
            }

    async def _process_results(
        self,
        results: List[ScrapingResult],
        target_config: Dict[str, Any]
    ) -> List[ScrapingResult]:
        """Apply filters and post-processors to results"""
        processed_results = results.copy()

        # Apply result filters
        for result_filter in self.result_filters:
            processed_results = [r for r in processed_results if result_filter(r, target_config)]

        # Apply post-processors
        for post_processor in self.post_processors:
            processed_results = await post_processor(processed_results, target_config)

        return processed_results

    def add_result_filter(self, filter_func: Callable[[ScrapingResult, Dict[str, Any]], bool]):
        """Add a filter function to exclude certain results"""
        self.result_filters.append(filter_func)

    def add_post_processor(self, processor_func: Callable):
        """Add a post-processor function for result enhancement"""
        self.post_processors.append(processor_func)

    async def _store_mission_results(self, mission_results: Dict[str, Any]):
        """Store scraping results in the knowledge base"""
        if not self.knowledge_base:
            return

        try:
            for target_result in mission_results['targets']:
                for scraping_result in target_result['scraping_results']:
                    if scraping_result['success'] and scraping_result['extracted_data']:
                        # Prepare document for knowledge base
                        document = {
                            'content': json.dumps(scraping_result['extracted_data'], indent=2),
                            'metadata': {
                                'source_url': scraping_result['url'],
                                'scraping_mission_id': mission_results['mission_id'],
                                'scraped_at': scraping_result['metadata'].get('timestamp'),
                                'content_type': 'scraped_data',
                                'target_objective': target_result['request']['objective']
                            }
                        }

                        # Store in knowledge base
                        await self.knowledge_base.add_document(document)

            self.logger.info(f"Stored mission results in knowledge base: {mission_results['mission_id']}")

        except Exception as e:
            self.logger.error(f"Failed to store mission results: {str(e)}")

    def _calculate_mission_statistics(self, mission_results: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate comprehensive statistics for the mission"""
        total_targets = len(mission_results['targets'])
        total_scrapes = sum(len(t['scraping_results']) for t in mission_results['targets'])
        successful_scrapes = sum(
            len([r for r in t['scraping_results'] if r['success']])
            for t in mission_results['targets']
        )

        return {
            'total_targets': total_targets,
            'total_scrapes': total_scrapes,
            'successful_scrapes': successful_scrapes,
            'success_rate': successful_scrapes / total_scrapes if total_scrapes > 0 else 0,
            'targets_with_data': len([t for t in mission_results['targets']
                                    if any(r['extracted_data'] for r in t['scraping_results'])]),
            'average_pages_per_target': total_scrapes / total_targets if total_targets > 0 else 0,
            'session_stats': self.session_stats.copy()
        }


# Example usage and integration patterns
class ScrapingMissionBuilder:
    """Builder pattern for creating complex scraping missions"""

    def __init__(self):
        self.mission_config = {
            'targets': [],
            'constraints': {},
            'output_config': {}
        }

    def add_target(
        self,
        url: str,
        objective: str = "Extract all relevant content",
        authentication: Optional[Dict[str, Any]] = None,
        custom_steps: Optional[List[Dict[str, Any]]] = None,
        custom_selectors: Optional[List[Dict[str, Any]]] = None
    ) -> 'ScrapingMissionBuilder':
        """Add a target to the scraping mission"""
        target = {
            'url': url,
            'objective': objective
        }

        if authentication:
            target['authentication'] = authentication
        if custom_steps:
            target['steps'] = custom_steps
        if custom_selectors:
            target['selectors'] = custom_selectors

        self.mission_config['targets'].append(target)
        return self

    def set_rate_limiting(
        self,
        requests_per_minute: int = 30,
        delay_between_requests: float = 2.0
    ) -> 'ScrapingMissionBuilder':
        """Set rate limiting constraints"""
        self.mission_config['constraints'].update({
            'requests_per_minute': requests_per_minute,
            'delay_between_requests': delay_between_requests
        })
        return self

    def set_authentication(
        self,
        username: str,
        password: str,
        login_url: str,
        username_selector: str = "#username",
        password_selector: str = "#password",
        submit_selector: str = "input[type=submit]"
    ) -> 'ScrapingMissionBuilder':
        """Set global authentication for all targets"""
        self.mission_config['authentication'] = {
            'required': True,
            'username': username,
            'password': password,
            'login_url': login_url,
            'selectors': {
                'username': username_selector,
                'password': password_selector,
                'submit': submit_selector
            }
        }
        return self

    def enable_content_analysis(
        self,
        summarize_content: bool = True,
        extract_entities: bool = True,
        sentiment_analysis: bool = False
    ) -> 'ScrapingMissionBuilder':
        """Enable advanced content analysis features"""
        self.mission_config['output_config'].update({
            'summarize_content': summarize_content,
            'extract_entities': extract_entities,
            'sentiment_analysis': sentiment_analysis
        })
        return self

    def build(self) -> Dict[str, Any]:
        """Build the final mission configuration"""
        self.mission_config['mission_id'] = f"mission_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return self.mission_config.copy()


# Example usage scenarios
async def example_ecommerce_scraping():
    """Example: Scraping product information from e-commerce sites"""

    # Build mission using the builder pattern
    mission = (ScrapingMissionBuilder()
        .add_target(
            url="https://example-store.com/products/laptops",
            objective="Extract laptop product details including name, price, specifications, and reviews",
            custom_selectors=[
                {
                    "name": "product_name",
                    "selector": "h1.product-title",
                    "extract_type": "text"
                },
                {
                    "name": "price",
                    "selector": ".price-current",
                    "extract_type": "text"
                },
                {
                    "name": "specifications",
                    "selector": ".product-specs li",
                    "extract_type": "text",
                    "multiple": True
                }
            ]
        )
        .add_target(
            url="https://competitor-store.com/laptops",
            objective="Extract competing laptop prices for comparison"
        )
        .set_rate_limiting(requests_per_minute=20, delay_between_requests=3.0)
        .enable_content_analysis(summarize_content=True, extract_entities=True)
        .build()
    )

    # Execute the mission
    orchestrator = ScrapingOrchestrator(
        driver_type='selenium',
        headless=True
    )

    # Add custom post-processor for price comparison
    async def price_comparison_processor(results, target_config):
        """Extract and normalize price data for comparison"""
        for result in results:
            if 'price' in result.extracted_data:
                # Add price normalization logic here
                result.metadata['normalized_price'] = extract_price_number(result.extracted_data['price'])
        return results

    orchestrator.add_post_processor(price_comparison_processor)

    # Execute mission
    mission_results = await orchestrator.execute_scraping_mission(mission)

    return mission_results

async def example_news_monitoring():
    """Example: Monitor news sites for specific topics"""

    mission = (ScrapingMissionBuilder()
        .add_target(
            url="https://news-site.com/technology",
            objective="Extract technology news articles with headlines, summaries, and publication dates",
            custom_selectors=[
                {
                    "name": "headlines",
                    "selector": "h2.article-title a",
                    "extract_type": "text",
                    "multiple": True
                },
                {
                    "name": "summaries",
                    "selector": ".article-summary",
                    "extract_type": "text",
                    "multiple": True
                }
            ]
        )
        .set_rate_limiting(requests_per_minute=15)
        .enable_content_analysis(
            summarize_content=True,
            extract_entities=True,
            sentiment_analysis=True
        )
        .build()
    )

    orchestrator = ScrapingOrchestrator()

    # Add filter to only keep articles about AI/ML
    def ai_ml_filter(result: ScrapingResult, target_config: Dict[str, Any]) -> bool:
        if not result.success or not result.extracted_data:
            return False

        content_text = str(result.extracted_data).lower()
        ai_keywords = ['artificial intelligence', 'machine learning', 'deep learning', 'neural network']

        return any(keyword in content_text for keyword in ai_keywords)

    orchestrator.add_result_filter(ai_ml_filter)

    return await orchestrator.execute_scraping_mission(mission)

def extract_price_number(price_text: str) -> Optional[float]:
    """Helper function to extract numeric price from text"""
    import re
    price_match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
    return float(price_match.group()) if price_match else None


# Integration with existing AI-parrot infrastructure
async def integrate_with_knowledge_base(kb_store: KnowledgeBaseStore):
    """Example of full integration with AI-parrot knowledge base"""

    orchestrator = ScrapingOrchestrator(
        knowledge_base=kb_store,
        auto_store_results=True
    )

    # Custom post-processor that uses text loaders for content processing
    async def knowledge_base_processor(results, target_config):
        """Process scraped content using AI-parrot text loaders"""
        from ..loaders.text import TextLoader

        for result in results:
            if result.success and result.extracted_data:
                # Create temporary text file with scraped content
                content = json.dumps(result.extracted_data, indent=2)

                # Use text loader to process and chunk content
                loader = TextLoader(
                    source=content,
                    chunk_size=800,
                    chunk_overlap=100
                )

                # Process content into chunks
                chunks = await loader.process_documents()

                # Add processed chunks to result metadata
                result.metadata['processed_chunks'] = len(chunks)
                result.metadata['content_processed'] = True

        return results

    orchestrator.add_post_processor(knowledge_base_processor)

    return orchestrator
