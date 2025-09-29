"""
ScrapingAgent for AI-Parrot
LLM-powered agent that makes intelligent decisions about web scraping
Updated to better integrate with current WebScrapingTool architecture
"""
from typing import Dict, List, Any, Optional, Literal
import json
import re
import logging
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from ..abstract import AbstractBot
from ...tools.scraping import (
    WebScrapingTool,
    ScrapingStep,
    ScrapingSelector,
    ScrapingResult
)
from .templates import (
    BESTBUY_TEMPLATE,
    AMAZON_TEMPLATE,
    EBAY_TEMPLATE
)
from .models import (
    ScrapingPlanSchema
)


class ScrapingAgent(AbstractBot):
    """
    Intelligent web scraping agent that uses LLM to:
    - Analyze web pages and determine optimal scraping strategies
    - Generate navigation steps based on page structure
    - Adapt selectors based on content analysis
    - Handle dynamic content and authentication flows
    - Recommend optimal browser configurations
    """

    def __init__(
        self,
        name: str = "WebScrapingAgent",
        browser: Literal['chrome', 'firefox', 'edge', 'safari', 'undetected'] = 'chrome',
        driver_type: Literal['selenium', 'playwright'] = 'selenium',
        headless: bool = True,
        mobile: bool = False,
        mobile_device: Optional[str] = None,
        auto_install: bool = True,
        **kwargs
    ):
        # Enhanced system prompt for web scraping
        system_prompt = self._build_scraping_system_prompt()

        super().__init__(
            name=name,
            system_prompt=system_prompt,
            **kwargs
        )

        # Store browser configuration for dynamic adjustments
        self.browser_config = {
            'browser': browser,
            'driver_type': driver_type,
            'headless': headless,
            'mobile': mobile,
            'mobile_device': mobile_device,
            'auto_install': auto_install,
            **kwargs
        }

        # Initialize scraping tool with configuration
        self.scraping_tool = WebScrapingTool(**self.browser_config)
        self.tool_manager.register_tool(self.scraping_tool)
        self.logger = logging.getLogger(f"AI-Parrot.ScrapingAgent")

        # Scraping context and memory
        self.scraping_history: List[Dict[str, Any]] = []
        self.site_knowledge: Dict[str, Dict[str, Any]] = {}

        # Site-specific templates and guidance
        self.scraping_templates = self._initialize_templates()

        # Browser capability knowledge
        self.browser_capabilities = {
            'chrome': {
                'mobile_emulation': True,
                'undetected_mode': True,
                'performance_options': True,
                'best_for': ['SPA', 'heavy_js', 'mobile_testing']
            },
            'firefox': {
                'mobile_emulation': False,
                'undetected_mode': False,
                'performance_options': True,
                'best_for': ['privacy', 'legacy_sites', 'debugging']
            },
            'edge': {
                'mobile_emulation': True,
                'undetected_mode': False,
                'performance_options': True,
                'best_for': ['enterprise', 'windows_specific']
            },
            'safari': {
                'mobile_emulation': False,
                'undetected_mode': False,
                'performance_options': False,
                'best_for': ['apple_ecosystem', 'webkit_testing']
            },
            'undetected': {
                'mobile_emulation': True,
                'undetected_mode': True,
                'performance_options': True,
                'best_for': ['anti_bot', 'stealth_scraping', 'protected_sites']
            }
        }

    def _initialize_templates(self) -> Dict[str, Dict[str, Any]]:
        """Initialize site-specific scraping templates and guidance"""
        return {
            'bestbuy.com': BESTBUY_TEMPLATE,
            'amazon.com': AMAZON_TEMPLATE,
            'ebay.com': EBAY_TEMPLATE,
            'generic_ecommerce': {
                'search_steps': [
                    {
                        'action': 'navigate',
                        'target': '{url}',
                        'description': 'Navigate to target site'
                    },
                    {
                        'action': 'fill',
                        'target': 'input[type="search"], input[name*="search"], input[placeholder*="search"]',
                        'value': '{search_term}',
                        'description': 'Fill most common search input patterns'
                    },
                    {
                        'action': 'click',
                        'target': 'button[type="submit"], input[type="submit"], .search-button',
                        'description': 'Click search button'
                    }
                ],
                'product_selectors': [
                    {
                        'name': 'products',
                        'selector': '.product, .item, .listing',
                        'extract_type': 'html',
                        'multiple': True
                    }
                ],
                'guidance': 'Generic e-commerce patterns. May need site-specific adjustments.'
            }
        }

    def _build_scraping_system_prompt(self) -> str:
        """Build specialized system prompt for web scraping tasks"""
        return """You are an expert web scraping agent with advanced capabilities in:

1. **Web Page Analysis**: Analyzing HTML structure, identifying key elements, and understanding page layouts
2. **Navigation Strategy**: Creating step-by-step navigation plans for complex user journeys
3. **Content Extraction**: Determining optimal selectors for extracting specific data
4. **Error Handling**: Adapting to dynamic content, handling timeouts, and recovering from failures
5. **Authentication**: Managing login flows, sessions, and security measures
6. **Browser Optimization**: Recommending optimal browser configurations based on target sites

**Available Browser Options:**
- chrome: Default, best performance, mobile emulation, wide compatibility
- firefox: Good privacy, stable, good for debugging
- edge: Enterprise-friendly, good performance
- safari: Apple ecosystem, webkit testing
- undetected: Anti-detection features, stealth scraping

**Core Responsibilities:**
- Analyze user scraping requirements and website structure
- Generate detailed navigation steps (ScrapingStep objects)
- Create precise content selectors (ScrapingSelector objects)
- Recommend optimal browser configuration for target sites
- Adapt strategies based on scraping results and feedback
- Provide insights about scraped content and suggest improvements

**Available Actions:**
- navigate: Go to a specific URL
- click: Click on elements (buttons, links, etc.)
- fill: Fill form fields with data
- wait: Wait for specific conditions or elements
- scroll: Scroll to load dynamic content
- authenticate: Handle login/authentication flows
- await_human: Pause automation; a human completes login/SSO/MFA in the browser. Resume when a selector/URL/title condition is met.
- await_keypress: Pause until the operator presses ENTER in the console.
- await_browser_event: Wait for a real page event (keyboard/overlay button/custom event/localStorage/predicate)

**Selector Types:**
- CSS selectors: Standard CSS syntax (.class, #id, element[attribute])
- XPath: For complex element selection
- Tag-based: Direct HTML tag selection

**Browser Configuration Recommendations:**
- Use 'undetected' browser for sites with anti-bot protection
- Use 'chrome' with mobile=True for mobile-responsive testing
- Use 'firefox' for sites that work better with Gecko engine
- Enable headless=False for debugging complex interactions
- Use custom user agents and mobile devices for specific testing

**Best Practices:**
- Always provide detailed descriptions for each step
- Use specific, robust selectors that are less likely to break
- Include appropriate wait conditions for dynamic content
- Plan authentication flows carefully with proper error handling
- Consider mobile responsiveness and different viewport sizes
- Recommend browser configuration based on site characteristics

When given a scraping task, analyze the requirements thoroughly and create a comprehensive plan that maximizes success while being respectful of website resources and terms of service.
"""

    async def analyze_scraping_request(
        self,
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze a scraping request and generate an execution plan with browser recommendations

        Args:
            request: Dictionary containing:
                - target_url: URL to scrape
                - objective: What data to extract
                - authentication: Login details if needed
                - constraints: Rate limiting, ethical guidelines
                - preferred_browser: Optional browser preference
                - use_template: Whether to use site-specific templates (default: True)

        Returns:
            Dictionary with execution plan including steps, selectors, and browser config
        """
        target_url = request.get('target_url', '')
        objective = request.get('objective', 'General content extraction')
        use_template = request.get('use_template', True)
        steps = request.get('steps', [])

        # Check for site-specific templates
        template_guidance = ""
        suggested_steps = []
        suggested_selectors = []

        if use_template and target_url:
            domain = self._extract_domain(target_url)
            if domain:
                # Check for exact domain match
                template = self.scraping_templates.get(domain)
                if not template:
                    # Check for partial domain matches
                    for template_domain, template_data in self.scraping_templates.items():
                        if template_domain in domain or domain in template_domain:
                            template = template_data
                            break

                if template:
                    template_guidance = f"\n\n**MANDATORY TEMPLATE FOR {domain.upper()}:**"
                    template_guidance += "\n**IMPORTANT:** These selectors are VERIFIED and TESTED. You MUST use these exact values.\n"
                    # Customize template steps with actual search term
                    if 'search_steps' in template and any(term in objective.lower() for term in ['search', 'product', 'find', 'extract']):
                        search_term = self._extract_search_term_from_objective(objective)
                        suggested_steps = self._customize_template_steps(
                            template['search_steps'], {
                                'search_term': search_term,
                                'url': target_url
                            }
                        )
                        template_guidance += f"\n\n**SUGGESTED STEPS (customized for '{search_term}'):**\n"
                        for i, step in enumerate(suggested_steps):
                            template_guidance += f"{i+1}. {step['action']}: {step.get('description', step['target'])}\n"

                    if 'product_selectors' in template:
                        suggested_selectors = template['product_selectors']
                        template_guidance += f"\n\n** SELECTORS:**\n"
                        for sel in suggested_selectors:
                            template_guidance += f"- {sel['name']}: {sel['selector']}\n"
                    template_guidance += "\n⚠️ CRITICAL: Use the exact 'target' values above. Do not substitute with '#gh-search-input' or other guesses.\n"
        elif steps:
            # use suggested steps from user:
            template_guidance += f"\n\n**SUGGESTED STEPS:**\n"
            for step in steps:
                template_guidance += f"- {step}\n"

        prompt = f"""
Analyze this web scraping request and create a comprehensive execution plan:

**Target URL:** {target_url}
**Objective:** {objective}
**Authentication Required:** {request.get('authentication', {}).get('required', False)}
**Special Requirements:** {request.get('constraints', 'None')}
**Current Browser Config:** {json.dumps(self.browser_config, indent=2)}

{template_guidance}

Please provide:
1. A detailed analysis of the scraping challenge
2. Recommended browser configuration (browser type, mobile mode, headless, etc.)
3. Step-by-step navigation plan (as JSON array of ScrapingStep objects)
4. Content extraction selectors (as JSON array of ScrapingSelector objects)
5. Risk assessment and mitigation strategies
6. Expected challenges and fallback options

**Browser Capabilities Available:**
{json.dumps(self.browser_capabilities, indent=2)}

**CRITICAL INSTRUCTIONS:**
1. For 'navigate' actions: target MUST be a complete URL starting with http:// or https://
2. For 'click', 'fill', 'wait' actions: target MUST be a CSS selector (e.g., '#id', '.class', 'button[type="submit"]')
3. NEVER use natural language descriptions as targets (e.g., "the search box" is WRONG, "#search-input" is CORRECT)
4. If template steps are provided above, use those EXACT targets - they are proven to work
5. Steps must be in logical order: navigate → wait → fill → click → wait for results
6. Never invent or hallucinate details about the page structure or content.

Provide your response as a structured plan following the ScrapingPlanSchema.
        """

        async with self._llm as client:
            response = await client.ask(
                prompt=prompt,
                system_prompt=self.system_prompt_template,
                model=self._llm_model,
                max_tokens=self._max_tokens,
                temperature=self._llm_temp,
                use_tools=True,
                structured_output=ScrapingPlanSchema
            )

        if isinstance(response.output, ScrapingPlanSchema):
            response = response.output
            merged_steps = []
            for i, template_step in enumerate(suggested_steps):
                merged = template_step.copy()
                # If LLM generated a corresponding step, take its metadata
                if i < len(response.steps):
                    llm_step = response.steps[i].model_dump()
                    # Keep template's target (proven to work)
                    # But use LLM's wait_condition and description if present
                    if llm_step.get('wait_condition'):
                        merged['wait_condition'] = llm_step['wait_condition']
                    if llm_step.get('description') and len(llm_step['description']) > len(merged.get('description', '')):
                        merged['description'] = llm_step['description']
                    # Use higher timeout if LLM suggests it
                    if llm_step.get('timeout', 10) > merged.get('timeout', 10):
                        merged['timeout'] = llm_step['timeout']
                merged_steps.append(merged)
            plan = {
                'steps': merged_steps,
                'selectors': suggested_selectors or [sel.model_dump() for sel in response.selectors],
                'browser_config': response.browser_config.model_dump(),
                'analysis': response.analysis,
                'risks': response.risks,
                'fallback_strategy': response.fallback_strategy,
                'parsed_successfully': True,
                'used_template': True
            }
        else:
            # Fallback if structured output not available
            content = self._safe_extract_text(response)
            plan = self._parse_scraping_plan(content)

        # If LLM didn't generate steps but we have template suggestions, use them as fallback
        if not plan.get('steps') and suggested_steps:
            self.logger.info("Using template steps as fallback")
            plan['steps'] = suggested_steps

        if not plan.get('selectors') and suggested_selectors:
            self.logger.info("Using template selectors as fallback")
            plan['selectors'] = suggested_selectors

        # Store this request in our knowledge base
        site_domain = self._extract_domain(target_url)
        if site_domain:
            self.site_knowledge[site_domain] = {
                'last_analyzed': datetime.now().isoformat(),
                'request': request,
                'plan': plan,
                'success_rate': 0.0,  # Will be updated based on results
                'recommended_config': plan.get('browser_config', {}),
                'used_template': bool(template_guidance)
            }

        return plan

    def _extract_search_term_from_objective(self, objective: str) -> str:
        """Extract search term from objective description"""
        # Look for product names, quotes, or specific terms
        # Try to find quoted terms first
        quoted_match = re.search(r'"([^"]+)"', objective)
        if quoted_match:
            return quoted_match.group(1)

        # Look for "for X" pattern
        for_match = re.search(r'\bfor\s+([^,\.]+)', objective, re.IGNORECASE)
        if for_match:
            return for_match.group(1).strip()

        # Look for product-like terms (words with numbers, proper nouns)
        product_match = re.search(r'\b([A-Z][a-z]*(?:\s+[A-Z0-9][a-z0-9]*)*(?:\s+\d+\w*)*)\b', objective)
        if product_match:
            return product_match.group(1)

        # Fallback: take last few words that might be product name
        words = objective.split()
        if len(words) >= 3:
            return ' '.join(words[-3:])
        elif len(words) >= 2:
            return ' '.join(words[-2:])
        else:
            return words[-1] if words else "product"

    def _customize_template_steps(self, template_steps: List[Dict], variables: Dict[str, str]) -> List[Dict]:
        """Customize template steps with actual values"""
        customized_steps = []
        for step in template_steps:
            customized_step = step.copy()

            # Replace variables in target and value fields
            if 'target' in customized_step:
                for var, value in variables.items():
                    customized_step['target'] = customized_step['target'].replace(f'{{{var}}}', value)

            if 'value' in customized_step and customized_step['value']:
                for var, value in variables.items():
                    customized_step['value'] = customized_step['value'].replace(f'{{{var}}}', value)

            customized_steps.append(customized_step)

        return customized_steps

    def add_scraping_template(self, domain: str, template: Dict[str, Any]):
        """Add or update a scraping template for a specific domain"""
        self.scraping_templates[domain] = template
        self.logger.info(f"Added scraping template for {domain}")

    async def execute_intelligent_scraping(
        self,
        request: Dict[str, Any],
        adaptive_config: bool = True
    ) -> List[ScrapingResult]:
        """
        Execute intelligent scraping with LLM-driven adaptations and browser optimization

        Args:
            request: Scraping request dictionary
            adaptive_config: Whether to adapt browser configuration based on LLM recommendations

        Returns:
            List of ScrapingResult objects
        """
        self.logger.info(
            f"Starting intelligent scraping for: {request.get('target_url')}"
        )

        try:
            # Step 1: Analyze and plan
            plan = await self.analyze_scraping_request(request)
            # some sanitization
            plan = self._sanitize_plan(plan, request)
            self.logger.debug(
                "Plan steps: %s", json.dumps(plan["steps"], indent=2)
            )
            self.logger.debug(
                "Sanitized selectors: %s", json.dumps(plan["selectors"], indent=2)
            )

            if not plan.get('steps'):
                self.logger.error("No scraping plan generated")
                return [ScrapingResult(
                    url=request.get('target_url', ''),
                    content='',
                    bs_soup=BeautifulSoup('', 'html.parser'),
                    success=False,
                    error_message="No scraping plan could be generated"
                )]

            # Step 2: Adapt browser configuration if recommended and allowed
            if adaptive_config and plan.get('browser_config'):
                await self._adapt_browser_configuration(plan['browser_config'])

            # Step 3: Ensure scraping tool is properly initialized
            if not hasattr(self.scraping_tool, 'driver') or self.scraping_tool.driver is None:
                await self.scraping_tool.initialize_driver()

            # Step 4: Execute initial scraping
            steps = [self._create_scraping_step(step) for step in plan['steps']]
            selectors = [self._create_scraping_selector(sel) for sel in plan.get('selectors', [])]

            results = await self.scraping_tool.execute_scraping_workflow(
                steps=steps,
                selectors=selectors,
                base_url=request.get('base_url', '')
            )

            # Step 5: Analyze results and adapt if necessary
            if results and not all(r.success for r in results):
                self.logger.info("Some scraping attempts failed, attempting recovery")
                results = await self._attempt_recovery(request, results, plan)

            # Step 6: Post-process and enhance results
            enhanced_results = await self._enhance_results(results, request)

            # Step 7: Update site knowledge
            self._update_site_knowledge(request, enhanced_results)

            return enhanced_results

        except Exception as e:
            self.logger.error(f"Intelligent scraping failed: {str(e)}")
            return [ScrapingResult(
                url=request.get('target_url', ''),
                content='',
                bs_soup=BeautifulSoup('', 'html.parser'),
                success=False,
                error_message=f"Scraping failed: {str(e)}"
            )]

    async def _adapt_browser_configuration(self, recommended_config: Dict[str, Any]):
        """
        Adapt browser configuration based on LLM recommendations
        """
        changes_made = []

        for key, value in recommended_config.items():
            if key in self.browser_config and self.browser_config[key] != value:
                old_value = self.browser_config[key]
                self.browser_config[key] = value
                changes_made.append(f"{key}: {old_value} -> {value}")

        if changes_made:
            self.logger.info(f"Adapting browser config: {', '.join(changes_made)}")

            # Reinitialize scraping tool with new configuration
            await self._reinitialize_scraping_tool()

    async def _reinitialize_scraping_tool(self):
        """Safely reinitialize the scraping tool with new configuration"""
        try:
            # Clean up existing tool
            if hasattr(self.scraping_tool, 'cleanup'):
                await self.scraping_tool.cleanup()

            # Create new tool with updated config
            self.scraping_tool = WebScrapingTool(**self.browser_config)

            # Re-register the tool
            if hasattr(self.tool_manager, 'unregister_tool'):
                self.tool_manager.unregister_tool('WebScrapingTool')
            self.tool_manager.register_tool(self.scraping_tool)

        except Exception as e:
            self.logger.warning(
                f"Failed to reinitialize scraping tool: {e}"
            )

    def _normalize_action(self, action: Optional[str]) -> str:
        return (action or 'navigate').strip().lower()

    def _normalize_target(self, target: Any) -> str:
        # Accept dicts like {"url": "..."} or {"selector": "..."} or lists
        if isinstance(target, dict):
            target = target.get('url') or target.get('selector') or target.get('text') or ''
        elif isinstance(target, (list, tuple)) and target:
            target = target[0]
        target = '' if target is None else str(target).strip()
        # Basic URL rescue: if it looks like a domain, prefix https://
        if target and (' ' not in target) and ('.' in target) and not target.startswith(('http://','https://','#','/')):
            target = f'https://{target}'
        return target

    def _normalize_value(self, value: Any) -> Optional[str]:
        return None if value is None else str(value)

    def _create_scraping_step(self, step_data: Dict[str, Any]) -> ScrapingStep:
        return ScrapingStep(
            action=self._normalize_action(step_data.get('action')),
            target=self._normalize_target(step_data.get('target', '')),
            value=self._normalize_value(step_data.get('value')),
            wait_condition=step_data.get('wait_condition'),
            timeout=step_data.get('timeout', 10),
            description=step_data.get('description', '')
        )

    def _create_scraping_selector(self, selector_data: Dict[str, Any]) -> ScrapingSelector:
        """Create ScrapingSelector object from dictionary, handling missing/odd fields"""
        name = selector_data.get('name', 'unnamed')
        selector = selector_data.get('selector', 'body')
        selector_type = selector_data.get('selector_type', 'css')
        extract_type = selector_data.get('extract_type', 'text')
        attribute = selector_data.get('attribute')
        multiple = selector_data.get('multiple', False)

        return ScrapingSelector(
            name=str(name),
            selector=str(selector),
            selector_type=str(selector_type),
            extract_type=str(extract_type),
            attribute=(str(attribute) if attribute is not None else None),
            multiple=bool(multiple)
        )

    async def recommend_browser_for_site(self, url: str) -> Dict[str, Any]:
        """
        Analyze a site and recommend optimal browser configuration
        """
        domain = self._extract_domain(url)

        # Check if we have prior knowledge
        if domain in self.site_knowledge:
            stored_config = self.site_knowledge[domain].get('recommended_config', {})
            if stored_config:
                return {
                    'source': 'historical_data',
                    'config': stored_config,
                    'confidence': 'high',
                    'reason': 'Based on previous successful scraping'
                }

        # Use LLM to analyze the site
        analysis_prompt = f"""
Analyze this website and recommend the optimal browser configuration for scraping:

**URL:** {url}
**Available Browsers:** {list(self.browser_capabilities.keys())}
**Browser Capabilities:** {json.dumps(self.browser_capabilities, indent=2)}

Please analyze the site characteristics and recommend:
1. Best browser choice (chrome, firefox, edge, safari, undetected)
2. Whether to use headless mode
3. Whether mobile emulation would be useful
4. Any special configuration options
5. Reasoning for your recommendations

Consider factors like:
- Site complexity (SPA, heavy JavaScript, etc.)
- Anti-bot protection
- Mobile responsiveness
- Authentication requirements
- Known compatibility issues

Provide your recommendation as a JSON object with configuration parameters.
        """

        try:
            async with self._llm as client:
                response = await client.ask(
                    prompt=analysis_prompt,
                    system_prompt=self.system_prompt_template,
                    model=self._llm_model,
                    max_tokens=self._max_tokens,
                    temperature=self._llm_temp,
                    use_tools=True,
                )

            # Parse recommendation from response
            content = self._safe_extract_text(response)
            recommendation = self._parse_browser_recommendation(content)

            return {
                'source': 'llm_analysis',
                'config': recommendation,
                'confidence': 'medium',
                'reason': 'Based on LLM analysis of site characteristics',
                'full_analysis': content
            }

        except Exception as e:
            self.logger.warning(f"Failed to get browser recommendation: {str(e)}")
            return {
                'source': 'fallback',
                'config': {'browser': 'chrome', 'headless': True},
                'confidence': 'low',
                'reason': 'Default fallback configuration'
            }

    def _parse_browser_recommendation(self, llm_response: str) -> Dict[str, Any]:
        """Parse browser configuration recommendation from LLM response"""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', llm_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))

            # Fallback: extract configuration from text
            config = {}

            # Extract browser type
            for browser, _ in self.browser_capabilities.items():
                if browser.lower() in llm_response.lower():
                    config['browser'] = browser
                    break

            # Extract headless recommendation
            if 'headless' in llm_response.lower():
                config['headless'] = 'false' not in llm_response.lower()

            # Extract mobile recommendation
            if 'mobile' in llm_response.lower():
                config['mobile'] = 'true' in llm_response.lower()

            return config if config else {'browser': 'chrome', 'headless': True}

        except Exception as e:
            self.logger.error(f"Failed to parse browser recommendation: {str(e)}")
            return {'browser': 'chrome', 'headless': True}

    async def _attempt_recovery(
        self,
        request: Dict[str, Any],
        failed_results: List[ScrapingResult],
        original_plan: Dict[str, Any]
    ) -> List[ScrapingResult]:
        """
        Attempt to recover from failed scraping using LLM analysis
        """
        # Analyze failures
        failure_analysis = []
        for result in failed_results:
            if not result.success:
                failure_analysis.append({
                    'url': result.url,
                    'error': result.error_message,
                    'content_available': bool(result.content)
                })

        recovery_prompt = f"""
The initial scraping attempt had some failures. Please analyze and suggest recovery strategies:

**Original Request:** {json.dumps(request, indent=2)}
**Failed Results:** {json.dumps(failure_analysis, indent=2)}
**Original Plan:** {json.dumps(original_plan, indent=2)}
**Current Browser Config:** {json.dumps(self.browser_config, indent=2)}

Please suggest:
1. Modified navigation steps to address the failures
2. Alternative selectors that might be more robust
3. Browser configuration changes that might help
4. Additional wait conditions or timing adjustments
5. Any authentication issues to address

Provide a recovery plan in the same format as before, including any browser config changes.
        """

        async with self._llm as client:
            recovery_response = await client.ask(
                prompt=recovery_prompt,
                system_prompt=self.system_prompt_template,
                model=self._llm_model,
                max_tokens=self._max_tokens,
                temperature=self._llm_temp,
                use_tools=True,
            )

        recovery_plan = self._parse_scraping_plan(self._safe_extract_text(recovery_response))

        if recovery_plan.get('steps'):
            self.logger.info("Executing recovery plan")

            # Apply any browser configuration changes
            if recovery_plan.get('browser_config'):
                await self._adapt_browser_configuration(recovery_plan['browser_config'])

            recovery_steps = [self._create_scraping_step(step) for step in recovery_plan['steps']]
            recovery_selectors = [self._create_scraping_selector(sel) for sel in recovery_plan.get('selectors', [])]

            recovery_results = await self.scraping_tool.execute_scraping_workflow(
                steps=recovery_steps,
                selectors=recovery_selectors,
                base_url=request.get('base_url', '')
            )

            # Combine successful results from both attempts
            combined_results = []
            for original, recovery in zip(failed_results, recovery_results):
                if recovery.success:
                    combined_results.append(recovery)
                elif original.success:
                    combined_results.append(original)
                else:
                    combined_results.append(recovery)  # Keep the latest attempt

            return combined_results

        return failed_results

    async def _enhance_results(
        self,
        results: List[ScrapingResult],
        request: Dict[str, Any]
    ) -> List[ScrapingResult]:
        """
        Enhance scraping results with LLM-powered content analysis
        """
        for result in results:
            if result.success and result.extracted_data:
                # Analyze content relevance and quality
                analysis_prompt = f"""
Analyze this scraped content for relevance and quality:

**Original Objective:** {request.get('objective', 'General extraction')}
**Extracted Data:** {json.dumps(result.extracted_data, indent=2, default=str)}
**URL:** {result.url}

Please provide:
1. Content quality score (1-10)
2. Relevance to objective (1-10)
3. Key insights or important information found
4. Suggestions for improving extraction
5. Data cleaning or formatting recommendations

Keep your analysis concise but comprehensive.
                """

                try:
                    async with self._llm as client:
                        analysis_response = await client.ask(
                            prompt=analysis_prompt,
                            system_prompt=self.system_prompt_template,
                            model=self._llm_model,
                            max_tokens=self._max_tokens,
                            temperature=self._llm_temp,
                            use_tools=True,
                        )
                    content = self._safe_extract_text(analysis_response)
                    # Add analysis to metadata
                    result.metadata.update({
                        'llm_analysis': content,
                        'analysis_timestamp': datetime.now().isoformat(),
                        'enhanced': True,
                        'browser_config_used': self.browser_config.copy()
                    })
                except Exception as e:
                    self.logger.warning(f"Content analysis failed: {str(e)}")

        return results

    def _looks_like_url(self, s: str) -> bool:
        try:
            s = (s or "").strip()
            if not s:
                return False
            return s.startswith(("http://", "https://")) or ('.' in s and ' ' not in s)
        except Exception:
            return False

    def _coerce_list_of_dicts(self, maybe_list):
        if maybe_list is None:
            return []
        if isinstance(maybe_list, dict):
            out = []
            for k, v in maybe_list.items():
                if isinstance(v, dict):
                    vv = v.copy()
                    vv.setdefault("name", k)
                    out.append(vv)
                else:
                    out.append({"name": str(k), "selector": str(v)})
            return out
        if isinstance(maybe_list, (list, tuple, set)):
            out = []
            for item in maybe_list:
                out.append(item if isinstance(item, dict) else {"selector": str(item)})
            return out
        return [{"selector": str(maybe_list)}]

    def _sanitize_steps(self, steps_raw, request_url: str) -> list[dict]:
        allowed = {"navigate", "click", "fill", "wait", "scroll", "authenticate", "await_human", "await_keypress", "await_browser_event"}
        steps: list[dict] = []
        for s in self._coerce_list_of_dicts(steps_raw):
            action = self._normalize_action(s.get("action"))
            if action not in allowed:
                continue
            target = self._normalize_target(s.get("target"))
            value = self._normalize_value(s.get("value"))

            # If navigate target isn't a real URL, force it to request_url
            if action == "navigate" and (not target or not self._looks_like_url(target)):
                target = request_url or target

            # For non-navigate actions, ensure target is a plausible CSS selector
            if action in {"click", "fill", "wait"}:
                # pick the first of comma-separated list if present
                if target and "," in target:
                    target = target.split(",")[0].strip()
                # reject blatant prose targets
                if target and (len(target) > 150 or " the " in target.lower()):
                    target = ""  # will be filtered below

            steps.append({
                "action": action,
                "target": target or "",
                "value": value,
                "wait_condition": s.get("wait_condition"),
                "timeout": s.get("timeout", 10),
                "description": s.get("description", "")
            })

        # Ensure we start with a valid navigate
        has_nav = any(st["action"] == "navigate" for st in steps)
        if not has_nav and request_url:
            steps.insert(0, {
                "action": "navigate",
                "target": request_url,
                "value": None,
                "wait_condition": None,
                "timeout": 15,
                "description": "Navigate to target URL"
            })
        else:
            for st in steps:
                if st["action"] == "navigate":
                    if not self._looks_like_url(st["target"]) and request_url:
                        st["target"] = request_url
                    break
        return steps

    def _sanitize_selectors(self, selectors_raw) -> list[dict]:
        cleaned: list[dict] = []
        bad_prefixes = (".0", "#0")  # guard against things like ".0.0.1"
        ip_like = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$')

        for sel in self._coerce_list_of_dicts(selectors_raw):
            selector = sel.get("selector") or sel.get("css") or sel.get("target")
            name = sel.get("name") or selector
            if not selector:
                continue
            selector = str(selector).strip()
            name = str(name)

            # Drop IPs or clearly invalid CSS like ".0.0.1"
            if selector.startswith(bad_prefixes) or ip_like.match(selector):
                continue
            # Very weak CSS plausibility check
            if not any(ch in selector for ch in ('.', '#', '[', '>', ':')) and ' ' not in selector:
                # allow tag-only selectors like 'a', 'h2' by whitelisting when short
                if selector.lower() not in {"a", "h1", "h2", "h3", "p", "span", "div"}:
                    continue

            cleaned.append({
                "name": name,
                "selector": selector,
                "selector_type": str(sel.get("selector_type", "css")),
                "extract_type": str(sel.get("extract_type", "text")),
                "attribute": (str(sel["attribute"]) if sel.get("attribute") is not None else None),
                "multiple": bool(sel.get("multiple", True))
            })
        return cleaned

    def _sanitize_plan(self, plan: dict, request: dict) -> dict:
        url = request.get("target_url") or request.get("base_url") or ""
        plan = dict(plan or {})
        plan["steps"] = self._sanitize_steps(plan.get("steps") or [], url)
        plan["selectors"] = self._sanitize_selectors(plan.get("selectors") or [])
        bcfg = plan.get("browser_config")
        if not isinstance(bcfg, dict):
            bcfg = {}
        plan["browser_config"] = bcfg
        return plan

    def _parse_scraping_plan(self, llm_response: str) -> Dict[str, Any]:
        """
        Parse LLM response to extract structured scraping plan
        """
        try:
            plan = {
                'steps': [],
                'selectors': [],
                'browser_config': {},
                'analysis': llm_response,
                'parsed_successfully': False
            }

            # Extract JSON sections from the response
            json_blocks = re.findall(r'```json\s*(\{.*?\}|\[.*?\])\s*```', llm_response, re.DOTALL)

            for block in json_blocks:
                try:
                    parsed = json.loads(block)
                    if isinstance(parsed, list):
                        # Could be steps or selectors
                        if parsed and 'action' in str(parsed[0]):
                            plan['steps'] = parsed
                        elif parsed and 'selector' in str(parsed[0]):
                            plan['selectors'] = parsed
                    elif isinstance(parsed, dict):
                        # Could be browser config
                        if any(key in parsed for key in ['browser', 'headless', 'mobile']):
                            plan['browser_config'] = parsed
                except json.JSONDecodeError:
                    continue

            # Fallback: try to extract from text
            if not plan['steps']:
                plan['steps'] = self._extract_steps_from_text(llm_response)

            if not plan['selectors']:
                plan['selectors'] = self._extract_selectors_from_text(llm_response)

            plan['parsed_successfully'] = bool(plan['steps'] or plan['selectors'])
            return plan

        except Exception as e:
            self.logger.error(f"Failed to parse scraping plan: {str(e)}")
            return {
                'steps': [],
                'selectors': [],
                'browser_config': {},
                'analysis': llm_response,
                'parsed_successfully': False,
                'parse_error': str(e)
            }

    def _extract_steps_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Fallback method to extract steps from unstructured text"""
        steps = []

        # Look for step patterns in text
        step_patterns = [
            r'navigate to (.*?)[\n\.]',
            r'click on (.*?)[\n\.]',
            r'fill (.*?) with (.*?)[\n\.]',
            r'wait for (.*?)[\n\.]',
            r'scroll to (.*?)[\n\.]'
        ]

        actions = ['navigate', 'click', 'fill', 'wait', 'scroll']

        for i, pattern in enumerate(step_patterns):
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    # For fill action
                    steps.append({
                        'action': actions[i],
                        'target': match[0].strip(),
                        'value': match[1].strip() if len(match) > 1 else None,
                        'description': f"{actions[i].title()} {match[0].strip()}"
                    })
                else:
                    steps.append({
                        'action': actions[i],
                        'target': match.strip(),
                        'description': f"{actions[i].title()} {match.strip()}"
                    })

        return steps

    def _extract_selectors_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Fallback method to extract selectors from unstructured text"""
        selectors = []

        # Look for selector patterns
        css_selectors = re.findall(r'[\.#][\w-]+(?:\s*[\.#][\w-]+)*', text)

        for i, selector in enumerate(css_selectors):
            selectors.append({
                'name': f'selector_{i+1}',
                'selector': selector.strip(),
                'selector_type': 'css',
                'extract_type': 'text'
            })

        return selectors

    def _extract_domain(self, url: str) -> Optional[str]:
        """Extract domain from URL"""
        try:
            parsed = urlparse(url)
            return parsed.netloc if parsed.netloc else None
        except:
            return None

    def _update_site_knowledge(
        self,
        request: Dict[str, Any],
        results: List[ScrapingResult]
    ):
        """Update our knowledge base about specific sites"""
        domain = self._extract_domain(request.get('target_url', ''))
        if domain and domain in self.site_knowledge:
            successful_results = [r for r in results if r.success]
            success_rate = len(successful_results) / len(results) if results else 0.0

            self.site_knowledge[domain].update({
                'success_rate': success_rate,
                'last_scrape': datetime.now().isoformat(),
                'total_attempts': self.site_knowledge[domain].get('total_attempts', 0) + 1,
                'last_successful_config': self.browser_config.copy() if success_rate > 0.5 else None
            })

    async def get_site_recommendations(self, url: str) -> Dict[str, Any]:
        """Get comprehensive recommendations for scraping a specific site"""
        domain = self._extract_domain(url)
        recommendations = {
            'domain': domain,
            'browser_recommendation': None,
            'scraping_strategy': None,
            'historical_data': None
        }

        # Get browser recommendation
        browser_rec = await self.recommend_browser_for_site(url)
        recommendations['browser_recommendation'] = browser_rec

        # Get historical data if available
        if domain in self.site_knowledge:
            knowledge = self.site_knowledge[domain]
            recommendations['historical_data'] = {
                'success_rate': knowledge.get('success_rate', 0.0),
                'last_successful_scrape': knowledge.get('last_scrape'),
                'total_attempts': knowledge.get('total_attempts', 0),
                'last_successful_config': knowledge.get('last_successful_config')
            }

        # Generate comprehensive strategy recommendations
        strategy_prompt = f"""
Provide comprehensive scraping strategy recommendations for this site:

**Domain:** {domain}
**URL:** {url}
**Browser Recommendation:** {json.dumps(browser_rec, indent=2)}
**Historical Data:** {json.dumps(recommendations.get('historical_data', {}), indent=2)}

Please suggest:
1. Overall scraping approach and strategy
2. Timing and rate limiting recommendations
3. Common challenges and how to handle them
4. Authentication strategies if needed
5. Content extraction best practices
6. Error handling and recovery strategies
        """

        try:
            async with self._llm as client:
                strategy_response = await client.ask(
                    prompt=strategy_prompt,
                    system_prompt=self.system_prompt_template,
                    model=self._llm_model,
                    max_tokens=self._max_tokens,
                    temperature=self._llm_temp,
                    use_tools=True,
                )
            recommendations['scraping_strategy'] = self._safe_extract_text(strategy_response)
        except Exception as e:
            self.logger.warning(f"Failed to generate strategy recommendations: {str(e)}")
            recommendations['scraping_strategy'] = "Unable to generate strategy recommendations"

        return recommendations

    async def cleanup(self):
        """Clean up resources"""
        if hasattr(self.scraping_tool, 'cleanup'):
            await self.scraping_tool.cleanup()

    def get_available_templates(self) -> Dict[str, str]:
        """Get list of available scraping templates"""
        return {domain: template.get('guidance', 'No guidance available')
                for domain, template in self.scraping_templates.items()}

    def get_template_for_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Get the best matching template for a given URL"""
        domain = self._extract_domain(url)
        if not domain:
            return None

        # Check for exact match
        if domain in self.scraping_templates:
            return self.scraping_templates[domain]

        # Check for partial matches
        for template_domain, template_data in self.scraping_templates.items():
            if template_domain in domain or domain in template_domain:
                return template_data

        return None
