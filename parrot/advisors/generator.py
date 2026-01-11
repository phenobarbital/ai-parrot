# parrot/advisors/generator.py
"""
LLM-Powered Question Generator for Product Selection.

Analyzes a product catalog and generates optimal discriminant questions.
"""
from typing import List, Dict, Any, Optional, Union, Type
from datetime import datetime
import json
import hashlib

from navconfig.logging import logging
from ..clients.base import AbstractClient
from ..stores.abstract import AbstractStore
from .models import ProductSpec
from .questions import (
    QuestionSet,
    DiscriminantQuestion,
    AnswerOption,
    ValueMapping,
    AnswerType,
    QuestionCategory,
    QuestionGenerationResponse,
    GeneratedQuestion,
    FeatureAnalyzer,
    CatalogAnalysis
)


# ─────────────────────────────────────────────────────────────────────────────
# Generation Prompt
# ─────────────────────────────────────────────────────────────────────────────

QUESTION_GENERATION_PROMPT = """You are an expert product advisor designing a guided selection wizard.

## Your Task
Analyze the product catalog below and generate a set of discriminant questions that will help narrow down product selection efficiently.

## Catalog Analysis
{catalog_analysis}

## Products Summary
{products_summary}

## Requirements for Questions

1. **Prioritization**: Order questions by their ability to eliminate products quickly:
   - First: Questions about USE CASE (why they need it) - highest discrimination
   - Second: Questions about SPACE/SIZE constraints - often eliminates many products
   - Third: Questions about BUDGET - clear filter
   - Fourth: Questions about specific FEATURES - for final narrowing
   - Last: PREFERENCE questions (style, color) - least discriminating

2. **Question Design**:
   - Use conversational, friendly language
   - Provide a shorter voice-optimized version
   - For choice questions, limit to 4-5 options maximum
   - Options should map clearly to product attributes

3. **Value Mappings**:
   - Each question must clearly map to filterable product attributes
   - Include how to interpret common response variations

4. **Smart Skipping**:
   - Identify questions that become irrelevant based on previous answers
   - Note dependencies between questions

## Output Format
Generate {target_question_count} questions as a JSON object matching this schema:
```json
{{
  "questions": [
    {{
      "question_text": "What will you primarily use this for?",
      "question_text_voice": "What's the main purpose?",
      "category": "use_case",
      "answer_type": "single_choice",
      "options": [
        {{"label": "Storage", "value": "storage", "description": "General storage for tools, equipment"}},
        {{"label": "Workshop", "value": "workshop", "description": "Working space for projects"}}
      ],
      "maps_to_feature": "use_case",
      "discrimination_power": 0.7,
      "priority_reason": "Use case is the strongest discriminator, eliminating ~70% of products",
      "follow_up_text": "Great choice!",
      "skip_if_feature": null
    }}
  ],
  "analysis_summary": "Brief summary of what makes products different",
  "key_discriminating_features": ["use_case", "footprint", "price"],
  "recommended_question_order": ["use_case", "space", "budget", "feature"]
}}
```

## Important Notes
- discrimination_power should reflect actual elimination rates from the catalog analysis
- For numeric questions (like space), include practical interpretations
- Consider that users may not know exact measurements - provide reference points
- Questions should feel helpful, not interrogative

Generate the questions now:"""


SPACE_QUESTION_TEMPLATE = """Based on the dimension analysis:
- Width range: {width_min} - {width_max} ft
- Depth range: {depth_min} - {depth_max} ft
- Footprint range: {footprint_min} - {footprint_max} sq ft

Create a space/size question that:
1. Asks about available space in a conversational way
2. Provides reference points (e.g., "about the size of a parking space")
3. Maps responses to footprint filtering"""


# ─────────────────────────────────────────────────────────────────────────────
# Question Generator Class
# ─────────────────────────────────────────────────────────────────────────────

class QuestionGenerator:
    """
    Generates discriminant questions for a product catalog using LLM analysis.
    
    Usage:
        generator = QuestionGenerator(llm=my_llm_client)
        question_set = await generator.generate(products, catalog_id="sheds_2024")
        
        # Questions are cached - subsequent calls return cached version
        question_set = await generator.generate(products, catalog_id="sheds_2024")
    """
    
    def __init__(
        self,
        llm: AbstractClient,
        cache_store: Optional[AbstractStore] = None,
        target_question_count: int = 8,
        min_discrimination_power: float = 0.2,
    ):
        """
        Initialize the question generator.
        
        Args:
            llm: LLM client for generating questions
            cache_store: Optional store for caching generated questions
            target_question_count: Target number of questions to generate
            min_discrimination_power: Minimum discrimination power to include
        """
        self.llm = llm
        self.cache_store = cache_store
        self.target_question_count = target_question_count
        self.min_discrimination_power = min_discrimination_power
        self.logger = logging.getLogger("QuestionGenerator")
    
    async def generate(
        self,
        products: List[ProductSpec],
        catalog_id: str,
        force_regenerate: bool = False,
        additional_context: str = ""
    ) -> QuestionSet:
        """
        Generate discriminant questions for a product catalog.
        
        Args:
            products: List of products to analyze
            catalog_id: Identifier for caching
            force_regenerate: If True, regenerate even if cached
            additional_context: Extra context to provide to LLM
            
        Returns:
            QuestionSet with generated questions
        """
        # Check cache first
        cache_key = self._get_cache_key(products, catalog_id)
        
        if not force_regenerate and self.cache_store:
            cached = await self._get_cached(cache_key)
            if cached:
                self.logger.info(f"Using cached questions for {catalog_id}")
                return cached
        
        self.logger.info(f"Generating questions for {catalog_id} ({len(products)} products)")
        
        # Step 1: Analyze catalog
        analyzer = FeatureAnalyzer(products)
        analysis = analyzer.analyze()
        
        # Step 2: Build prompt
        prompt = self._build_prompt(products, analysis, additional_context)
        
        # Step 3: Call LLM with structured output
        response = await self._call_llm(prompt)
        
        # Step 4: Post-process and validate
        question_set = self._build_question_set(
            response, 
            analysis, 
            catalog_id,
            products
        )
        
        # Step 5: Cache the result
        if self.cache_store:
            await self._cache_questions(cache_key, question_set)
        
        self.logger.info(f"Generated {question_set.question_count} questions")
        return question_set
    
    def _build_prompt(
        self,
        products: List[ProductSpec],
        analysis: CatalogAnalysis,
        additional_context: str
    ) -> str:
        """Build the generation prompt with catalog context."""
        
        # Format catalog analysis
        analysis_text = self._format_analysis(analysis)
        
        # Format products summary (not full details, just discriminating info)
        products_summary = self._format_products_summary(products, analysis)
        
        prompt = QUESTION_GENERATION_PROMPT.format(
            catalog_analysis=analysis_text,
            products_summary=products_summary,
            target_question_count=self.target_question_count
        )
        
        if additional_context:
            prompt += f"\n\n## Additional Context\n{additional_context}"
        
        return prompt
    
    def _format_analysis(self, analysis: CatalogAnalysis) -> str:
        """Format catalog analysis for the prompt."""
        lines = [
            f"**Total Products**: {analysis.total_products}",
            f"**Categories**: {', '.join(analysis.categories)}",
            "",
            "**Top Discriminating Features** (by elimination power):"
        ]
        
        for fa in analysis.feature_analyses[:8]:
            lines.append(
                f"  - {fa.feature_name}: {fa.unique_values_count} values, "
                f"{fa.discrimination_power:.0%} discrimination power, "
                f"{fa.coverage:.0%} coverage"
            )
            if fa.value_counts:
                top_values = list(fa.value_counts.items())[:4]
                values_str = ", ".join(f"{k}({v})" for k, v in top_values)
                lines.append(f"    Values: {values_str}")
        
        lines.append("")
        lines.append("**Dimension Ranges**:")
        for dim, ranges in analysis.dimension_ranges.items():
            lines.append(f"  - {dim}: {ranges.get('min', 0):.1f} - {ranges.get('max', 0):.1f}")
        
        lines.append("")
        lines.append("**Price Analysis**:")
        pr = analysis.price_range
        if pr:
            lines.append(f"  - Range: ${pr.get('min', 0):,.0f} - ${pr.get('max', 0):,.0f}")
            lines.append(f"  - Average: ${pr.get('avg', 0):,.0f}")
        
        lines.append("")
        lines.append("**Use Cases**:")
        for uc, count in analysis.use_case_counts.items():
            lines.append(f"  - {uc}: {count} products")
        
        return "\n".join(lines)
    
    def _format_products_summary(
        self, 
        products: List[ProductSpec],
        analysis: CatalogAnalysis
    ) -> str:
        """Format products for the prompt (abbreviated)."""
        lines = ["| ID | Name | Category | Price | Footprint | Use Cases |"]
        lines.append("|---|---|---|---|---|---|")
        
        for p in products[:20]:  # Limit to avoid token overflow
            footprint = f"{p.dimensions.footprint:.0f} sqft" if p.dimensions else "N/A"
            price = f"${p.price:,.0f}" if p.price else "N/A"
            use_cases = ", ".join(p.use_cases[:3]) if p.use_cases else "N/A"
            
            lines.append(
                f"| {p.product_id} | {p.name[:30]} | {p.category} | "
                f"{price} | {footprint} | {use_cases} |"
            )
        
        if len(products) > 20:
            lines.append(f"| ... | ({len(products) - 20} more products) | ... | ... | ... | ... |")
        
        return "\n".join(lines)
    
    async def _call_llm(self, prompt: str) -> QuestionGenerationResponse:
        """Call LLM to generate questions."""
        try:
            async with self.llm as client:
                response = await client.ask(
                    prompt=prompt,
                    structured_output=QuestionGenerationResponse,
                    temperature=0.3,  # Lower temperature for more consistent output
                    max_tokens=16384
                )
                
                # Extract structured output
                if hasattr(response, 'output') and response.output:
                    if isinstance(response.output, QuestionGenerationResponse):
                        return response.output
                    elif isinstance(response.output, dict):
                        return QuestionGenerationResponse(**response.output)
                
                # Fallback: try to parse from response text
                if hasattr(response, 'response'):
                    import re
                    json_match = re.search(r'\{[\s\S]*\}', response.response)
                    if json_match:
                        data = json.loads(json_match.group())
                        return QuestionGenerationResponse(**data)
                
                raise ValueError("Could not extract structured response from LLM")
                
        except Exception as e:
            self.logger.error(f"LLM generation failed: {e}")
            # Return fallback questions
            return self._get_fallback_questions()
    
    def _build_question_set(
        self,
        response: QuestionGenerationResponse,
        analysis: CatalogAnalysis,
        catalog_id: str,
        products: List[ProductSpec]
    ) -> QuestionSet:
        """Convert LLM response to QuestionSet."""
        questions = []
        
        for i, gen_q in enumerate(response.questions):
            # Convert generated question to full DiscriminantQuestion
            question = self._convert_generated_question(gen_q, i, analysis)
            
            # Validate discrimination power against actual catalog
            actual_power = self._calculate_actual_discrimination(
                question, products
            )
            question.discrimination_power = actual_power
            
            # Only include if meets minimum threshold
            if actual_power >= self.min_discrimination_power:
                questions.append(question)
        
        # Sort by priority (higher first)
        questions.sort(key=lambda q: q.priority, reverse=True)
        
        # Add standard questions if missing
        questions = self._ensure_standard_questions(questions, analysis, products)
        
        return QuestionSet(
            catalog_id=catalog_id,
            questions=questions,
            generated_at=datetime.utcnow(),
            generated_by_model=getattr(self.llm, 'model', None) or 'unknown',
            total_products=len(products),
            coverage={q.question_id: len(products) for q in questions}
        )
    
    def _convert_generated_question(
        self,
        gen_q: GeneratedQuestion,
        index: int,
        analysis: CatalogAnalysis
    ) -> DiscriminantQuestion:
        """Convert GeneratedQuestion to full DiscriminantQuestion."""
        # Map category string to enum
        category_map = {
            "use_case": QuestionCategory.USE_CASE,
            "space": QuestionCategory.SPACE,
            "budget": QuestionCategory.BUDGET,
            "feature": QuestionCategory.FEATURE,
            "preference": QuestionCategory.PREFERENCE,
            "timeline": QuestionCategory.TIMELINE,
        }
        category = category_map.get(gen_q.category.lower(), QuestionCategory.FEATURE)
        
        # Map answer type
        answer_type_map = {
            "single_choice": AnswerType.SINGLE_CHOICE,
            "multi_choice": AnswerType.MULTI_CHOICE,
            "numeric": AnswerType.NUMERIC,
            "numeric_range": AnswerType.NUMERIC_RANGE,
            "boolean": AnswerType.BOOLEAN,
            "free_text": AnswerType.FREE_TEXT,
        }
        answer_type = answer_type_map.get(
            gen_q.answer_type.lower(), 
            AnswerType.SINGLE_CHOICE
        )
        
        # Convert options - now gen_q.options are already AnswerOption objects
        options = None
        if gen_q.options:
            options = [
                AnswerOption(
                    label=opt.label,
                    value=opt.value if opt.value else opt.label.lower(),
                    description=opt.description
                )
                for opt in gen_q.options
            ]
        
        # Build value mappings from options
        value_mappings = []
        if options:
            for opt in options:
                value_mappings.append(ValueMapping(
                    response_pattern=f"(?i){opt.label}|{opt.value}",
                    criteria_key=gen_q.maps_to_feature,
                    criteria_value=opt.value
                ))
        
        # Calculate priority based on category and discrimination
        priority = self._calculate_priority(category, gen_q.discrimination_power)
        
        # Build skip_if
        skip_if = None
        if gen_q.skip_if_feature:
            skip_if = {gen_q.skip_if_feature: True}  # Skip if feature already determined
        
        return DiscriminantQuestion(
            question_id=f"q_{category.value}_{index}",
            question_text=gen_q.question_text,
            question_text_voice=gen_q.question_text_voice,
            category=category,
            answer_type=answer_type,
            options=options,
            maps_to_feature=gen_q.maps_to_feature,
            value_mappings=value_mappings,
            priority=priority,
            discrimination_power=gen_q.discrimination_power,
            skip_if=skip_if,
            follow_up_text=gen_q.follow_up_text
        )
    
    def _calculate_priority(
        self, 
        category: QuestionCategory, 
        discrimination_power: float
    ) -> int:
        """Calculate question priority (0-100)."""
        # Base priority by category
        category_base = {
            QuestionCategory.USE_CASE: 90,
            QuestionCategory.SPACE: 80,
            QuestionCategory.BUDGET: 70,
            QuestionCategory.FEATURE: 50,
            QuestionCategory.PREFERENCE: 30,
            QuestionCategory.TIMELINE: 20,
        }
        
        base = category_base.get(category, 50)
        
        # Adjust by discrimination power (-10 to +10)
        adjustment = int((discrimination_power - 0.5) * 20)
        
        return max(0, min(100, base + adjustment))
    
    def _calculate_actual_discrimination(
        self,
        question: DiscriminantQuestion,
        products: List[ProductSpec]
    ) -> float:
        """Calculate actual discrimination power against product catalog."""
        if not question.options:
            return question.discrimination_power  # Use LLM estimate
        
        # Count how products distribute across options
        option_counts = {opt.value: 0 for opt in question.options}
        other_count = 0
        
        for product in products:
            matched = False
            
            # Check use cases
            if question.maps_to_feature == "use_case":
                for opt in question.options:
                    if opt.value in product.use_cases:
                        option_counts[opt.value] = option_counts.get(opt.value, 0) + 1
                        matched = True
                        break
            
            # Check features
            else:
                feature = product.get_feature(question.maps_to_feature)
                if feature:
                    for opt in question.options:
                        if str(feature.value).lower() == str(opt.value).lower():
                            option_counts[opt.value] = option_counts.get(opt.value, 0) + 1
                            matched = True
                            break
            
            if not matched:
                other_count += 1
        
        # Calculate entropy-based discrimination
        total = sum(option_counts.values()) + other_count
        if total == 0:
            return 0.0
        
        # Ideal case: each option gets equal share
        # Discrimination = 1 - (max_count / total)
        max_count = max(option_counts.values()) if option_counts else total
        discrimination = 1 - (max_count / total)
        
        return round(discrimination, 2)
    
    def _ensure_standard_questions(
        self,
        questions: List[DiscriminantQuestion],
        analysis: CatalogAnalysis,
        products: List[ProductSpec]
    ) -> List[DiscriminantQuestion]:
        """Ensure standard questions are included if missing."""
        existing_categories = {q.category for q in questions}
        
        # Always need a space question if dimensions vary
        if (QuestionCategory.SPACE not in existing_categories and 
            analysis.dimension_ranges.get("footprint")):
            
            footprint = analysis.dimension_ranges["footprint"]
            questions.append(self._create_space_question(footprint, len(questions)))
        
        # Always need a budget question if prices vary
        if (QuestionCategory.BUDGET not in existing_categories and 
            analysis.price_range.get("min") != analysis.price_range.get("max")):
            
            questions.append(self._create_budget_question(
                analysis.price_range, 
                analysis.price_clusters,
                len(questions)
            ))
        
        return questions
    
    def _create_space_question(
        self, 
        footprint_range: Dict[str, float],
        index: int
    ) -> DiscriminantQuestion:
        """Create a standard space/dimensions question."""
        min_fp = footprint_range.get("min", 0)
        max_fp = footprint_range.get("max", 200)
        
        # Create meaningful size buckets
        small_max = min_fp + (max_fp - min_fp) * 0.33
        medium_max = min_fp + (max_fp - min_fp) * 0.66
        
        return DiscriminantQuestion(
            question_id=f"q_space_{index}",
            question_text="How much space do you have available for this?",
            question_text_voice="How much space do you have?",
            category=QuestionCategory.SPACE,
            answer_type=AnswerType.SINGLE_CHOICE,
            options=[
                AnswerOption(
                    label="Compact",
                    value="compact",
                    description=f"Up to {small_max:.0f} sq ft"
                ),
                AnswerOption(
                    label="Medium",
                    value="medium", 
                    description=f"{small_max:.0f} - {medium_max:.0f} sq ft"
                ),
                AnswerOption(
                    label="Large",
                    value="large",
                    description=f"Over {medium_max:.0f} sq ft"
                ),
                AnswerOption(
                    label="I have specific dimensions",
                    value="specific",
                    description="I'll provide exact measurements"
                ),
            ],
            maps_to_feature="max_footprint",
            value_mappings=[
                ValueMapping(
                    response_pattern=r"compact|small|limited",
                    criteria_key="max_footprint",
                    criteria_value=small_max,
                    is_range=True
                ),
                ValueMapping(
                    response_pattern=r"medium|moderate|average",
                    criteria_key="max_footprint", 
                    criteria_value=medium_max,
                    is_range=True
                ),
                ValueMapping(
                    response_pattern=r"large|big|plenty|lots",
                    criteria_key="max_footprint",
                    criteria_value=max_fp,
                    is_range=True
                ),
                ValueMapping(
                    response_pattern=r"(\d+)\s*[xX×by]\s*(\d+)",
                    criteria_key="available_space",
                    criteria_value=None,  # Will be parsed dynamically
                    is_range=True
                ),
            ],
            priority=80,
            discrimination_power=0.6,
            follow_up_text="Got it! That helps narrow things down.",
            clarification_hint="You can say things like '10 by 12 feet' or just 'medium size'"
        )
    
    def _create_budget_question(
        self,
        price_range: Dict[str, float],
        price_clusters: List[Dict[str, Any]],
        index: int
    ) -> DiscriminantQuestion:
        """Create a standard budget question."""
        min_price = price_range.get("min", 0)
        max_price = price_range.get("max", 10000)
        
        # Use clusters if available, otherwise create simple tiers
        if price_clusters:
            options = []
            for cluster in price_clusters:
                if cluster["name"] == "budget":
                    options.append(AnswerOption(
                        label="Budget-friendly",
                        value="budget",
                        description=f"Under ${cluster.get('max', min_price + 500):,.0f}"
                    ))
                elif cluster["name"] == "mid-range":
                    options.append(AnswerOption(
                        label="Mid-range",
                        value="mid-range",
                        description=f"${cluster.get('min', 500):,.0f} - ${cluster.get('max', 2000):,.0f}"
                    ))
                elif cluster["name"] == "premium":
                    options.append(AnswerOption(
                        label="Premium",
                        value="premium",
                        description=f"${cluster.get('min', 2000):,.0f}+"
                    ))
            
            options.append(AnswerOption(
                label="Flexible / Show all",
                value="flexible",
                description="Price isn't my main concern"
            ))
        else:
            third = (max_price - min_price) / 3
            options = [
                AnswerOption(label="Budget", value="budget", 
                           description=f"Under ${min_price + third:,.0f}"),
                AnswerOption(label="Mid-range", value="mid-range",
                           description=f"${min_price + third:,.0f} - ${min_price + 2*third:,.0f}"),
                AnswerOption(label="Premium", value="premium",
                           description=f"Over ${min_price + 2*third:,.0f}"),
                AnswerOption(label="Flexible", value="flexible",
                           description="Show all options"),
            ]
        
        return DiscriminantQuestion(
            question_id=f"q_budget_{index}",
            question_text="What's your budget range for this purchase?",
            question_text_voice="What's your budget?",
            category=QuestionCategory.BUDGET,
            answer_type=AnswerType.SINGLE_CHOICE,
            options=options,
            maps_to_feature="max_price",
            value_mappings=[
                ValueMapping(
                    response_pattern=r"budget|cheap|affordable|under",
                    criteria_key="max_price",
                    criteria_value=min_price + (max_price - min_price) * 0.33,
                    is_range=True
                ),
                ValueMapping(
                    response_pattern=r"mid|moderate|average",
                    criteria_key="max_price",
                    criteria_value=min_price + (max_price - min_price) * 0.66,
                    is_range=True
                ),
                ValueMapping(
                    response_pattern=r"\$?\s*(\d+[,\d]*)",
                    criteria_key="max_price",
                    criteria_value=None,
                    is_range=True
                ),
            ],
            priority=70,
            discrimination_power=0.5,
            follow_up_text="Thanks! I'll keep that in mind."
        )
    
    def _get_fallback_questions(self) -> QuestionGenerationResponse:
        """Return fallback questions if LLM fails."""
        return QuestionGenerationResponse(
            questions=[
                GeneratedQuestion(
                    question_text="What will you primarily use this for?",
                    question_text_voice="What's the main purpose?",
                    category="use_case",
                    answer_type="single_choice",
                    options=[
                        AnswerOption(label="Storage", value="storage"),
                        AnswerOption(label="Workspace", value="workspace"),
                        AnswerOption(label="Other", value="other"),
                    ],
                    maps_to_feature="use_case",
                    discrimination_power=0.6,
                    priority_reason="Use case is typically the best first filter",
                    follow_up_text="Got it!"
                ),
                GeneratedQuestion(
                    question_text="What's your budget range for this purchase?",
                    question_text_voice="What's your budget?",
                    category="budget",
                    answer_type="single_choice",
                    options=[
                        AnswerOption(label="Budget-friendly", value="budget"),
                        AnswerOption(label="Mid-range", value="mid-range"),
                        AnswerOption(label="Premium", value="premium"),
                        AnswerOption(label="Flexible", value="flexible"),
                    ],
                    maps_to_feature="max_price",
                    discrimination_power=0.5,
                    priority_reason="Budget helps filter quickly",
                    follow_up_text="Thanks!"
                ),
            ],
            analysis_summary="Fallback questions due to generation failure",
            key_discriminating_features=["use_case", "size", "price"],
            recommended_question_order=["use_case", "space", "budget"]
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    # Caching
    # ─────────────────────────────────────────────────────────────────────────
    
    def _get_cache_key(self, products: List[ProductSpec], catalog_id: str) -> str:
        """Generate cache key based on catalog content."""
        # Hash based on product IDs and key attributes
        content = json.dumps([
            {
                "id": p.product_id,
                "features": len(p.features),
                "use_cases": sorted(p.use_cases),
            }
            for p in sorted(products, key=lambda x: x.product_id)
        ])
        
        content_hash = hashlib.md5(content.encode()).hexdigest()[:12]
        return f"questions:{catalog_id}:{content_hash}"
    
    async def _get_cached(self, cache_key: str) -> Optional[QuestionSet]:
        """Retrieve cached question set."""
        if not self.cache_store:
            return None
        
        try:
            # Implementation depends on your cache store
            # This is a placeholder
            pass
        except Exception as e:
            self.logger.warning(f"Cache retrieval failed: {e}")
        
        return None
    
    async def _cache_questions(self, cache_key: str, question_set: QuestionSet) -> None:
        """Cache generated question set."""
        if not self.cache_store:
            return
        
        try:
            # Implementation depends on your cache store
            pass
        except Exception as e:
            self.logger.warning(f"Cache storage failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Function
# ─────────────────────────────────────────────────────────────────────────────

async def generate_discriminant_questions(
    products: List[ProductSpec],
    llm: AbstractClient,
    catalog_id: str = "default",
    **kwargs
) -> QuestionSet:
    """
    Convenience function to generate questions for a catalog.
    
    Usage:
        questions = await generate_discriminant_questions(
            products=my_products,
            llm=my_llm_client,
            catalog_id="sheds_2024"
        )
    """
    generator = QuestionGenerator(llm=llm, **kwargs)
    return await generator.generate(products, catalog_id)