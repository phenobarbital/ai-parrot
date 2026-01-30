import asyncio
from dataclasses import asdict as as_dict
from parrot.models.crew import CrewResult
from parrot.bots.orchestration import AgentCrew, FlowContext
from parrot.bots import Agent
from parrot.tools.google import GoogleSearchTool, GoogleSiteSearchTool
from parrot.tools.ibisworld import IBISWorldTool
from parrot.tools.yfinance import YFinanceTool


async def generating_crews():
   """
   This example demonstrates using different execution modes for different
   parts of a larger workflow. This shows how the three modes can complement
   each other in a real-world application.

   Scenario: Market Research Report Generation

   Phase 1 (Parallel): Gather data from multiple sources simultaneously
   Phase 2 (Flow): Process and analyze data with dependencies
   Phase 3 (Sequential): Refine and format the final report
   """
   print("\n" + "="*70)
   print("EXAMPLE 5: Hybrid Approach Using All Three Modes")
   print("="*70 + "\n")

   # Phase 1: Parallel data gathering
   print("Phase 1: Parallel Data Gathering")
   print("-" * 50)

   google_search = GoogleSearchTool()
   site_search = GoogleSiteSearchTool()
   ibis = IBISWorldTool()
   ticker_tool = YFinanceTool()

   site_prompt = """
Prioritize results from these authoritative sources and provide detailed findings with citations:
Statista: https://www.statista.com/
Forrester: https://www.forrester.com/
Gartner: https://www.gartner.com/
Deloitte: https://www2.deloitte.com/us/en.html
Ipsos: https://www.ipsos.com/
IbisWorld: https://www.ibisworld.com/
Ernst & Young: https://www.ey.com/
Euromonitor International: https://www.euromonitor.com/
Crunchbase: https://www.crunchbase.com/
Bloomberg: https://www.bloomberg.com/
Business Insider: https://www.businessinsider.com/
US Securities and Exchange Commission: https://www.sec.gov/
U.S. Census Bureau: https://www.census.gov/
Bureau of Economic Analysis: https://www.bea.gov/
Bureau of Labor Statistics: https://www.bls.gov/
Ibisworld: https://www.ibisworld.com/
Kantar: https://www.kantar.com/
IDC: https://www.idc.com/
McKinsey: https://www.mckinsey.com/
PwC: https://www.pwc.com/
Accenture: https://www.accenture.com/us-en
Dynata: https://www.dynata.com/
Nielsen: https://www.nielsen.com/
PitchBook: https://pitchbook.com/
DataFox: https://www.datafox.com/
Orbis by Bureau van Dijk: https://www.bvdinfo.com/en-us/our-products/data/international/orbis

IMPORTANT: Provide comprehensive findings with:
- Specific data points with sources and dates
- Multiple perspectives when available
- Detailed explanations, not just summaries
- All relevant statistics and metrics found
   """

   search_prompt = """
You are a Market Research Data Analyst specializing in comprehensive data gathering.

{site_prompt}

Your task is to:
1. Search multiple authoritative sources
2. Compile ALL relevant information found (not just summaries)
3. Include specific data points, statistics, and metrics
4. Cite all sources with URLs
5. Organize findings by subtopic
6. Provide detailed context and explanations

Output format:
## [Topic Area]
### Finding 1: [Title]
- **Source:** [URL and publication date]
- **Data:** [Specific statistics, numbers, percentages]
- **Context:** [Detailed explanation]
- **Relevance:** [Why this matters]

### Finding 2: [Title]
...

DO NOT summarize or condense. Include ALL relevant findings.
   """

   ibis_prompt = """
Use the ibisworld (IBISWorldTool) to find key statistics (market size, growth rate, customer demographics, etc.) of specific industry with no details:
Example user queries: `Provide me the key statistics of Pet Stores Industry in the US market and global market`
Example Output:
```
Key Statistics:
1. Market Size: $XX billion (2023)
2. Growth Rate: X% CAGR (2023-2028)
3. Global Market is expected to grow from $32.4 billion in 2021 to $38.5 billion by 2027 at a CAGR of 6.5%
According to IbisWorld:
1. Global Market is expected to grow from $20.4 billion in 2020 to $40.5 billion by 2025 at a CAGR of 5.5%
```
   """

   services_prompt = """
Use the google_search (GoogleSearchTool) to find primary services (retailing, support, distribution, etc.) of specific industry with no details:
Example user queries: `Provide me the primary services of Pet Stores Industry`
Example Output:
```
Primary Services:
1. Retailing of pet food and supplies
2. Pet grooming and boarding services
3. Veterinary services
4. Pet training and behavior consultation
```
Provide me the current % market share and brief explanation of products and services:
Output (Examples):
```
Market Share:
1. * Pet Food: 45.7%
2. * Pet Supplies: 30.2%
3. * Pet Services: 24.1%
```

   """

   key_statistics_prompt = f"""
You are a Statistical Research Specialist focused on gathering comprehensive quantitative data.
Use the google_site_search (GoogleSiteSearchTool) and google_site_search (GoogleSiteSearchTool) to find key statistics (market size, growth rate, customer demographics, etc.) of specific industry with no details:

{site_prompt}

{ibis_prompt}

Your mission is to collect ALL available statistics for the specified industry:

1. **Market Size & Value:**
   - Current market value (USD)
   - Historical data (past 3-5 years)
   - Projected future values
   - Growth rates and CAGR
   - Regional breakdowns

2. **Market Share:**
   - Top 10+ companies with percentages
   - Market concentration metrics
   - Competitive landscape indicators

3. **Demographics:**
   - Customer segments with percentages
   - Age groups, income levels, geographic distribution
   - Behavioral patterns and preferences

4. **Performance Metrics:**
   - Revenue figures
   - Profit margins
   - Employee statistics
   - Number of establishments

5. **Growth Indicators:**
   - Year-over-year growth
   - Compound annual growth rates
   - Future projections (5-10 years)

Include ALL statistics found, with:
- Exact figures and percentages
- Source citations with dates
- Comparison data when available
- Context for each statistic

DO NOT filter or reduce data. Report everything comprehensively.
   """

   data_agents = [
      Agent(
         name="industry_overview",
         system_prompt=f"""
You are an Industry Overview Specialist.

{search_prompt}

Provide a comprehensive overview covering:
1. **Industry Definition:** Detailed description of the industry scope
2. **Key Characteristics:** Major features and attributes
3. **Current State:** Overall health and maturity level
4. **Recent Developments:** Major events, changes, or news
5. **Industry Evolution:** Historical context and trajectory

Include detailed paragraphs for each section with multiple data points and examples.
Minimum output: 500+ words with comprehensive coverage.
         """,
         llm='google',
         tools=[google_search, site_search, ibis],
      ),
      Agent(
         name="services_data",
         system_prompt=services_prompt,
         llm='google',
         tools=[google_search, site_search, ibis],
      ),
      Agent(
         name="market_data",
         system_prompt="""Research market data, market size, growth, trends, and forecasts.

collect data of market size (current and historical), growth rate, trends (consumer behavior, technology, etc.),
forecasts (short-term and long-term) for a specified industry.

Provide the current % market share of the top 5 companies in the industry and a brief analysis of their competitive positioning.
         """,
         llm='google',
         tools=[google_search, site_search, ibis],
      ),
      Agent(
         name="major_markets",
         system_prompt=f"""
You are a Market Segmentation & Geography Analyst.

{search_prompt}

Analyze major markets across multiple dimensions:

1. **Geographic Markets:**
   - Regional breakdown (US regions, international)
   - Market size by geography
   - Growth rates by region
   - Regional preferences and differences

2. **Customer Segments:**
   - Demographic segments (age, income, etc.) with %
   - Behavioral segments
   - B2B vs B2C breakdown
   - Enterprise vs SMB (if applicable)

3. **Channel Markets:**
   - Distribution channel breakdown
   - Online vs offline percentages
   - Emerging channel trends

4. **Vertical Markets:**
   - Industry verticals served
   - Application areas
   - Use case scenarios

Provide detailed analysis with specific percentages and data.
Minimum output: 400+ words.
         """,
         llm='google',
         tools=[google_search, site_search]
      ),
      Agent(
         name="competitor_data",
         system_prompt=f"""
You are a Competitive Intelligence Analyst.

{search_prompt}

Conduct deep competitive analysis:

1. **Major Competitors:**
   - Top 15+ companies with profiles
   - Market share for each (%)
   - Revenue figures
   - Geographic presence
   - Product/service portfolios

2. **Competitive Strategies:**
   - Differentiation approaches
   - Pricing strategies
   - Marketing approaches
   - Innovation focus areas

3. **Competitive Positioning:**
   - Market leaders vs followers
   - Niche players and specialists
   - New entrants and disruptors
   - Strategic groupings

4. **Strengths & Weaknesses:**
   - Key advantages by competitor
   - Vulnerabilities and challenges
   - Competitive advantages

5. **Recent Activities:**
   - M&A activity
   - Product launches
   - Strategic partnerships
   - Market expansions

Provide comprehensive competitor profiles with all available data.
Minimum output: 700+ words.
            """,
         llm='google',
         tools=[google_search, site_search, ibis]
      ),
      Agent(
         name='similar_industries',
         system_prompt=f"""
You are an Industry Ecosystem Analyst.

{search_prompt}

Research related and similar industries:

1. **Adjacent Industries:**
   - Industries with overlapping products/services
   - Market size comparisons
   - Growth rate comparisons
   - Cross-industry trends

2. **Upstream Industries:**
   - Suppliers and their characteristics
   - Supply chain dynamics

3. **Downstream Industries:**
   - Customer industries
   - Distribution channels

4. **Complementary Industries:**
   - Industries that enhance or support this one
   - Partnership opportunities
   - Ecosystem dynamics

5. **Competitive Industries:**
   - Alternative solutions
   - Substitutes and replacements
   - Competitive dynamics

Provide detailed analysis with market data for each related industry.
Minimum output: 400+ words.
         """,
         llm='google',
         tools=[google_search, site_search]
      ),
      Agent(
         name="distribution_channel",
         system_prompt=f"""
You are a Distribution Channel & Logistics Analyst.

{search_prompt}

Conduct comprehensive channel analysis:

1. **Primary Distribution Channels:**
   - Detailed description of each channel
   - Market share by channel (%)
   - Growth trends by channel
   - Profitability by channel

2. **Retail Channels:**
   - Physical retail presence
   - Retail formats and types
   - Geographic coverage

3. **Digital Channels:**
   - E-commerce platforms
   - Direct-to-consumer models
   - Marketplace presence
   - Digital sales percentage

4. **B2B Channels:**
   - Distributor networks
   - Dealer/reseller models
   - Direct sales approaches

5. **Channel Evolution:**
   - Emerging channels
   - Declining channels
   - Omnichannel strategies
   - Technology integration

6. **Logistics & Supply Chain:**
   - Fulfillment models
   - Inventory management
   - Delivery methods
   - Cost structures

Provide exhaustive channel analysis with specific data.
Minimum output: 500+ words.
         """,
         llm='google',
         tools=[google_search, site_search]
      ),
      Agent(
         name="financial_data",
         system_prompt=f"""
You are a Financial & Economic Analyst.

{search_prompt}

Gather comprehensive financial data:

1. **Revenue Data:**
   - Total industry revenue (current & historical)
   - Revenue by segment
   - Revenue by geography
   - Top company revenues

2. **Profit Metrics:**
   - Industry profit margins (gross, operating, net)
   - Profitability by segment
   - Profitability trends
   - Comparison to other industries

3. **Financial Ratios:**
   - ROI, ROE, ROA averages
   - Debt-to-equity ratios
   - Current ratios
   - Asset turnover

4. **Investment Data:**
   - VC/PE investment in the sector
   - M&A activity and valuations
   - IPO activity
   - Valuation multiples

5. **Economic Impact:**
   - Employment figures
   - Wage levels
   - Economic contribution
   - Tax implications

6. **Cost Structure:**
   - Major cost categories
   - Cost trends
   - Cost pressures

Include all financial data with sources and context.
Minimum output: 500+ words.
         """,
         llm='groq',
         model="meta-llama/llama-4-maverick-17b-128e-instruct",
         tools=[google_search, site_search, ticker_tool]
      ),
      Agent(
         name="cost_structure",
         system_prompt="""
Analyze cost structure, including fixed and variable costs.
collect data of cost structure (fixed costs, variable costs, cost drivers, etc.) for a specified industry.
Output (Examples):
```
Cost Structure:
1. Fixed Costs:
   - Rent and Utilities: 15%: Retail locations often require significant space, leading to higher rent and utility expenses.
   - Salaries and Wages: 25%: Due to the labor-intensive nature of the retail sector, wages are estimated to make up the second-highest expense for pet store operator.
   - Profit: 10%: Profit margins in the pet store industry can vary widely based on factors such as location, competition, and operational efficiency. On average, profit margins may range from 5% to 15%.
2. Variable Costs:
   - Inventory Costs: 30%: The cost of purchasing pet food, supplies, and other merchandise constitutes a significant portion of variable costs.
   - Marketing and Advertising: 10%: Effective marketing strategies are essential for attracting customers and driving sales in a competitive market.
   - Maintenance and Repairs: 5%: Regular maintenance and repairs are necessary to keep retail locations and equipment in good working condition.
```
         """,
         llm='groq',
         model="meta-llama/llama-4-maverick-17b-128e-instruct",
         tools=[google_search, site_search, ibis]
      ),
      Agent(
         name="industry_revenue",
         system_prompt="""
Analyze industry revenue streams and profitability.
collect data of revenue streams (product sales, services, subscriptions, etc.) for a specified industry.
- Rank this industry based on revenue and profitability among similar industries in US market.
- Provide me the major revenue streams and a brief analysis of their contribution to overall profitability.
- How atomized is the industry in terms of revenue generation among competitors?
         """,
         tools=[google_search, site_search]
      ),
      Agent(
         name="supply_demand_data",
         system_prompt=f"""
You are a Supply & Demand Economics Analyst.

{search_prompt}

Analyze supply and demand dynamics:

1. **Demand Analysis:**
   - Current demand levels (quantified)
   - Historical demand trends
   - Demand drivers and influences
   - Demand seasonality/cyclicality
   - Demand elasticity
   - Future demand projections

2. **Supply Analysis:**
   - Current supply capacity
   - Supply constraints
   - Production/service capacity
   - Supply growth trends
   - New capacity additions

3. **Supply-Demand Balance:**
   - Current market equilibrium
   - Oversupply/undersupply situations
   - Price implications
   - Competitive intensity impacts

4. **Consumer Behavior:**
   - Purchase patterns
   - Decision factors
   - Loyalty metrics
   - Switching behavior

5. **Market Dynamics:**
   - Entry/exit rates
   - Capacity utilization
   - Inventory levels
   - Lead times

Provide quantitative analysis with specific metrics and trends.
Minimum output: 400+ words.
         """,
         llm='google',
         tools=[google_search, site_search]
      ),
      Agent(
         name="key_statistics",
         system_prompt=key_statistics_prompt,
         llm='groq',
         model="meta-llama/llama-4-maverick-17b-128e-instruct",
         tools=[google_search, site_search, ibis]
      ),
      Agent(
         name="key_statistics_business",
         system_prompt="""
            Please provide me with the most recent estimate of the number of businesses that are currently competing in the specified industry within the US market.

            Put the focus on delivering the latest available data regarding the count of active businesses operating in this industry sector.
            Prioritize following sources:
            - Gartner
            - IbisWorld
            - Statista
            - U.S. Census Bureau
            - Bureau of Economic Analysis
         """,
         llm='groq',
         model="meta-llama/llama-4-maverick-17b-128e-instruct",
         tools=[google_search, site_search, ibis]
      ),
      Agent(
         name="industry_structure",
         system_prompt=f"""
You are an Industry Structure & Organization Analyst.

{search_prompt}

Analyze comprehensive industry structure:

1. **Market Concentration:**
   - HHI (Herfindahl-Hirschman Index) if available
   - CR4/CR8 ratios (top 4/8 concentration)
   - Number of competitors by tier
   - Market fragmentation analysis

2. **Competition Level:**
   - Intensity of rivalry
   - Competitive factors
   - Price competition vs differentiation
   - Innovation competition

3. **Barriers to Entry:**
   - Capital requirements
   - Regulatory barriers
   - Technology barriers
   - Brand loyalty/switching costs
   - Distribution access
   - Scale economies required

4. **Industry Life Cycle:**
   - Current stage (emerging/growth/mature/decline)
   - Stage characteristics
   - Historical evolution
   - Future trajectory

5. **Structural Characteristics:**
   - Revenue volatility level
   - Capital intensity level
   - Regulation level
   - Technology change rate
   - Globalization level

6. **Value Chain Structure:**
   - Key activities
   - Value distribution
   - Integration levels

Rate each characteristic as Low/Medium/High with detailed justification.
Minimum output: 500+ words.
         """,
         tools=[google_search, site_search]
      ),
      Agent(
         name="external_drivers",
         system_prompt=f"""
You are an External Factors & Drivers Analyst.

{search_prompt}

Identify and analyze all external drivers:

1. **Economic Drivers:**
   - GDP growth impact
   - Interest rates and credit
   - Exchange rates (if relevant)
   - Consumer spending trends
   - Business investment levels
   - Inflation impacts

2. **Technological Drivers:**
   - Disruptive technologies
   - Automation trends
   - Digital transformation
   - R&D developments
   - Technology adoption rates

3. **Social & Demographic Drivers:**
   - Population trends
   - Age demographics
   - Lifestyle changes
   - Cultural shifts
   - Consumer preferences
   - Urbanization

4. **Regulatory & Political:**
   - Current regulations
   - Pending legislation
   - Regulatory trends
   - Political stability
   - Trade policies
   - Tax policies

5. **Environmental Factors:**
   - Sustainability trends
   - Climate change impacts
   - Resource availability
   - Green initiatives

6. **Industry-Specific Drivers:**
   - Unique factors affecting this industry
   - Cyclical factors
   - Seasonal factors

For each driver, provide:
- Quantified impact (% or specific metrics)
- Direction (positive/negative)
- Timeframe
- Supporting evidence and data

Minimum output: 600+ words with comprehensive coverage.
         """,
         tools=[google_search, site_search]
      ),
      Agent(
         name="new_players",
         system_prompt=f"""
You are a New Entrants & Innovation Tracker.

{search_prompt}

Research new players and market disruption:

1. **New Entrants (Last 2-3 years):**
   - Company profiles
   - Founding date and background
   - Funding raised (amounts and investors)
   - Business models
   - Product/service innovations
   - Market positioning
   - Growth metrics

2. **Startups & Disruptors:**
   - Emerging companies to watch
   - Innovative approaches
   - Technology differentiation
   - Target markets

3. **Market Entry Strategies:**
   - Entry modes observed
   - Pricing strategies
   - Go-to-market approaches
   - Differentiation tactics

4. **Expansion Patterns:**
   - Geographic expansion
   - Product line extensions
   - Market segment expansions
   - Strategic partnerships

5. **Traditional Player Responses:**
   - Incumbent reactions
   - Competitive moves
   - Innovation initiatives
   - Strategic adaptations

6. **Investment & Funding:**
   - Recent funding rounds
   - Investor interest trends
   - Valuation trends
   - M&A activity involving new players

Provide detailed profiles with all available data.
Minimum output: 500+ words.
         """,
         tools=[google_search, site_search]
      )
   ]
   for agent in data_agents:
      await agent.configure()
   # Phase 2: Flow-based analysis
   swot_analyzer = Agent(
      name="swot_analyzer",
      system_prompt="""
You are a Strategic SWOT Analysis Expert.

Based on all the data gathered, create a comprehensive SWOT analysis:

**STRENGTHS:**
- Industry strengths (minimum 8-10 points)
- Each point with detailed explanation
- Supporting data and evidence
- Quantified when possible

**WEAKNESSES:**
- Industry weaknesses (minimum 8-10 points)
- Detailed explanations
- Impact assessment
- Supporting evidence

**OPPORTUNITIES:**
- Growth opportunities (minimum 8-10 points)
- Market gaps
- Emerging trends to capitalize on
- Strategic possibilities
- Quantified potential when available

**THREATS:**
- External threats (minimum 8-10 points)
- Competitive threats
- Market risks
- Regulatory/economic challenges
- Impact assessment

For each SWOT element:
1. Provide detailed explanation (3-5 sentences)
2. Include supporting data from research
3. Assess magnitude/importance (Low/Medium/High)
4. Explain strategic implications

Create a comprehensive analysis document of 1000+ words.
Format as a structured report with clear sections and subsections.
      """,
      use_llm='google',
      tools=[google_search, site_search]
   )
   market_analyzer = Agent(
      name="market_analyzer",
      system_prompt="""
You are a Business Opportunity Identification Specialist.

Analyze the gathered data to identify specific business opportunities for:
- Retail service providers
- IT service providers
- Break and fix services
- Monitoring services
- Merchandisers
- Logistics providers
- Managed services

For each service provider type:

1. **Opportunity Areas:**
   - Specific gaps or needs (minimum 5 per type)
   - Market size for each opportunity
   - Growth potential
   - Competitive intensity

2. **Revenue Potential:**
   - Estimated market value
   - Pricing ranges
   - Margin expectations

3. **Entry Requirements:**
   - Capabilities needed
   - Investment required
   - Timeframe to market

4. **Success Factors:**
   - Critical success factors
   - Competitive advantages needed
   - Risks to mitigate

5. **Strategic Recommendations:**
   - Specific actions to take
   - Prioritization of opportunities
   - Implementation considerations

Provide a detailed opportunity matrix with quantified assessments.
Minimum output: 800+ words formatted as a comprehensive business opportunities report.
      """,
      use_llm='google',
      tools=[google_search, site_search]
   )
   new_player_analyzer = Agent(
      name="new_player_analyzer",
      system_prompt="""
- Are there opportunities for market consolidation given that there is not a well defined market leader in the retail services arena for the specified industry?
- Identify emerging competitors and startups that could disrupt the market dynamics.
      """,
      use_llm='google',
      tools=[google_search, site_search]
   )
   trend_analyzer = Agent(
      name="trend_analyzer",
      system_prompt="Identify key trends about the industry, including technological, consumer, and market trends.",
      use_llm='google',
      tools=[google_search, site_search]
   )
   risk_analyzer = Agent(
      name="risk_analyzer",
      system_prompt="""
You are a Risk Assessment & Management Expert.

Conduct comprehensive risk analysis covering:

1. **Market Risks:**
   - Demand risks (minimum 6 risk factors)
   - Supply risks
   - Competition risks
   - Each with:
     * Detailed description
     * Probability assessment (%)
     * Impact severity (Low/Medium/High)
     * Timeframe
     * Mitigation strategies

2. **Operational Risks:**
   - Supply chain risks
   - Technology risks
   - Execution risks
   - Scalability risks

3. **Financial Risks:**
   - Revenue volatility
   - Cost inflation
   - Funding/capital risks
   - Profitability risks

4. **Regulatory & Compliance Risks:**
   - Current regulatory challenges
   - Pending regulations
   - Compliance costs
   - Legal risks

5. **Strategic Risks:**
   - Disruption risks
   - Technological obsolescence
   - Competitive displacement
   - Business model risks

6. **External Risks:**
   - Economic downturn impacts
   - Geopolitical risks
   - Social/demographic shifts
   - Environmental risks

7. **Risk Mitigation Framework:**
   - Priority risks (top 10)
   - Mitigation strategies for each
   - Contingency plans
   - Monitoring approaches

Provide detailed risk register with:
- Risk description
- Probability (%)
- Impact severity
- Risk score
- Mitigation approach
- Residual risk

Minimum output: 800+ words in structured risk report format.
      """,
      use_llm='google',
      tools=[google_search, site_search]
   )
   opportunity_analyzer = Agent(
      name="opportunity_analyzer",
      system_prompt="""
You are a Growth Opportunities & Innovation Strategist.

Identify and evaluate all opportunities for growth and innovation:

1. **Market Growth Opportunities:**
   - Underserved segments (minimum 8 opportunities)
   - Geographic expansion potential
   - Customer segment expansion
   - Each opportunity with:
     * Detailed description
     * Market size estimate
     * Growth potential (%)
     * Investment required
     * Expected timeline
     * Success probability

2. **Product/Service Opportunities:**
   - New product categories
   - Service extensions
   - Innovation areas
   - Adjacent offerings

3. **Channel Opportunities:**
   - New distribution channels
   - Omnichannel approaches
   - Direct-to-consumer models
   - Partnership channels

4. **Technology Opportunities:**
   - Digital transformation
   - Automation potential
   - AI/ML applications
   - Platform opportunities

5. **Business Model Opportunities:**
   - Subscription models
   - Marketplace approaches
   - Platform models
   - As-a-service models

6. **Partnership & Collaboration:**
   - Strategic partnerships
   - M&A opportunities
   - Joint ventures
   - Ecosystem plays

7. **Innovation Opportunities:**
   - Disruptive innovations
   - Process innovations
   - Customer experience innovations

8. **Opportunity Prioritization:**
   - Top 10 opportunities ranked
   - Prioritization criteria:
     * Market attractiveness
     * Competitive positioning
     * Execution feasibility
     * Resource requirements
     * Risk level

Provide comprehensive opportunity assessment with:
- Detailed opportunity profiles
- Quantified potential (revenue, margin)
- Implementation roadmap
- Resource requirements
- Key success factors

Minimum output: 900+ words in structured opportunity report format.
      """,
      use_llm='google',
      tools=[google_search, site_search]
   )
   strategic_synthesizer = Agent(
      name="strategic_synthesizer",
      system_prompt="""
You are a Strategic Insights Synthesizer and Chief Strategist.

Synthesize ALL analysis inputs (SWOT, Trends, Market, Risks, Opportunities) into cohesive strategic insights:

**Your mission is to create a comprehensive Strategic Analysis Summary that:**

1. **Executive Summary:**
   - Key strategic insights (5-7 main takeaways)
   - Critical success factors
   - Major strategic imperatives

2. **Strategic Position Assessment:**
   - Current industry position
   - Competitive dynamics
   - Industry attractiveness
   - Strategic challenges

3. **Growth Strategy Framework:**
   - Recommended growth vectors
   - Market positioning strategy
   - Competitive strategy
   - Innovation strategy

4. **Strategic Priorities:**
   - Top 10 strategic priorities
   - Rationale for each
   - Implementation sequence
   - Resource allocation guidance

5. **Investment Thesis:**
   - Why invest in this industry?
   - Best opportunities identified
   - Risk-adjusted returns
   - Investment timeframe

6. **Strategic Recommendations:**
   - Specific strategic actions (minimum 15)
   - Short-term actions (0-12 months)
   - Medium-term actions (1-3 years)
   - Long-term actions (3-5 years)

7. **Success Metrics:**
   - KPIs to track
   - Milestones
   - Performance targets

8. **Risk Management Strategy:**
   - Top risks to manage
   - Mitigation approach
   - Contingency plans

**Format Requirements:**
- Comprehensive synthesis of 1200+ words
- Clear section headings
- Bullet points with detailed explanations
- Data-driven insights
- Actionable recommendations

Do NOT simply summarize. SYNTHESIZE insights across all analyses to create an integrated strategic perspective.
      """,
      use_llm='google',
      tools=[google_search, site_search]
   )

   analysis_agents = [
      swot_analyzer,
      trend_analyzer,
      market_analyzer,
      new_player_analyzer,
      risk_analyzer,
      opportunity_analyzer,
      strategic_synthesizer
   ]

   for agent in analysis_agents:
      await agent.configure()

   report_agents = [
      Agent(
         name="executive_summary_writer",
         system_prompt="""
You are an Executive Summary Specialist.

Create a compelling executive summary that:

1. **Overview (2-3 paragraphs):**
   - Industry scope and definition
   - Market size and growth
   - Key dynamics

2. **Key Findings (5-7 bullet points):**
   - Most important discoveries
   - Critical insights
   - Surprising findings

3. **Strategic Implications (3-4 paragraphs):**
   - What this means for stakeholders
   - Major opportunities
   - Key challenges

4. **Bottom Line (1 paragraph):**
   - Clear recommendation or conclusion
   - Investment perspective
   - Action orientation

Keep it concise but comprehensive (500-700 words).
Write for C-level executives who need the essence quickly.
         """,
         use_llm='google'
      ),
      Agent(
         name="comprehensive_report_compiler",
         system_prompt="""
You are a Master Report Compiler and Technical Writer.

Your critical mission: Compile ALL research findings into a comprehensive, professional market research report.

**Report Structure (MANDATORY):**

# COMPREHENSIVE MARKET RESEARCH REPORT
## [Industry Name]

---

## EXECUTIVE SUMMARY
[Executive summary from previous agent]

---

## TABLE OF CONTENTS
[Auto-generated from sections below]

---

## PART 1: MARKET INTELLIGENCE & DATA FINDINGS

### 1. Industry Overview
[Include ALL findings from industry_overview agent]
- Industry definition and scope
- Key characteristics
- Current state analysis
- Recent developments
- Historical evolution

### 2. Market Size & Dynamics
[Include ALL findings from market_data agent]
- Current market size with historical data
- Growth metrics and CAGR
- Market trends analysis
- Forecasts and projections
- Top companies analysis with market shares

### 3. Products & Services Analysis
[Include ALL findings from services_data agent]
- Primary offerings with market shares
- Secondary offerings
- Product/service mix breakdown
- Innovation and trends

### 4. Key Market Statistics
[Include ALL findings from key_statistics agent]
- Comprehensive statistics compilation
- Market metrics
- Performance indicators
- Demographic data

### 5. Major Markets & Segmentation
[Include ALL findings from major_markets agent]
- Geographic markets breakdown
- Customer segments analysis
- Channel markets
- Vertical markets

### 6. Competitive Landscape
[Include ALL findings from competitor_data agent]
- Major competitors profiles (Top 15+)
- Market share analysis
- Competitive strategies
- Competitive positioning
- Recent competitive activities

### 7. Distribution Channels
[Include ALL findings from distribution_channel agent]
- Channel breakdown with percentages
- Retail channels analysis
- Digital channels
- B2B channels
- Channel evolution
- Logistics and supply chain

### 8. Financial Analysis
[Include ALL findings from financial_data agent]
- Revenue data
- Profit metrics
- Financial ratios
- Investment data
- Economic impact
- Cost structure

### 9. Supply & Demand Dynamics
[Include ALL findings from supply_demand_data agent]
- Demand analysis
- Supply analysis
- Market balance
- Consumer behavior
- Market dynamics

### 10. Industry Structure
[Include ALL findings from industry_structure agent]
- Market concentration
- Competition level
- Barriers to entry
- Industry life cycle
- Structural characteristics
- Value chain

### 11. Similar & Related Industries
[Include ALL findings from similar_industries agent]
- Adjacent industries
- Upstream industries
- Downstream industries
- Complementary industries
- Competitive industries

### 12. External Drivers
[Include ALL findings from external_drivers agent]
- Economic drivers
- Technological drivers
- Social & demographic drivers
- Regulatory & political factors
- Environmental factors
- Industry-specific drivers

### 13. New Players & Market Disruption
[Include ALL findings from new_players agent]
- New entrants analysis
- Startups & disruptors
- Market entry strategies
- Expansion patterns
- Traditional player responses
- Investment & funding trends

---

## PART 2: STRATEGIC ANALYSIS

### 14. SWOT Analysis
[Include COMPLETE analysis from swot_analyzer]
- Detailed strengths (8-10 points)
- Detailed weaknesses (8-10 points)
- Detailed opportunities (8-10 points)
- Detailed threats (8-10 points)

### 15. Market Trends & Future Outlook
[Include COMPLETE analysis from trend_analyzer]
- Current trends (10+)
- Emerging trends (8+)
- Technology trends
- Consumer behavior trends
- Business model trends
- Competitive trends
- Trend implications

### 16. Business Opportunities Assessment
[Include COMPLETE analysis from market_analyzer]
- Opportunity areas by service type
- Revenue potential analysis
- Entry requirements
- Success factors
- Strategic recommendations

### 17. Risk Assessment
[Include COMPLETE analysis from risk_analyzer]
- Market risks
- Operational risks
- Financial risks
- Regulatory risks
- Strategic risks
- External risks
- Risk mitigation framework

### 18. Growth & Innovation Opportunities
[Include COMPLETE analysis from opportunity_analyzer]
- Market growth opportunities (8+)
- Product/service opportunities
- Channel opportunities
- Technology opportunities
- Business model opportunities
- Partnership opportunities
- Innovation opportunities
- Opportunity prioritization

### 19. Strategic Synthesis
[Include COMPLETE synthesis from strategic_synthesizer]
- Executive summary of strategic insights
- Strategic position assessment
- Growth strategy framework
- Strategic priorities (Top 10)
- Investment thesis
- Strategic recommendations (15+)
- Success metrics
- Risk management strategy

---

## PART 3: CONCLUSIONS & RECOMMENDATIONS

### 20. Conclusion & Key Takeaways
[From conclusion_writer agent]
- Summary of key findings
- Critical insights
- Major implications
- Forward-looking perspective

### 21. Strategic Recommendations Summary
[From conclusion_writer agent]
- Prioritized action items
- Implementation roadmap
- Resource considerations
- Success factors

---

## APPENDICES

### Appendix A: Data Sources
- List of all sources cited
- Source credibility assessment

### Appendix B: Methodology
- Research approach
- Data collection methods
- Analysis frameworks used

### Appendix C: Glossary
- Key terms and definitions

---

**CRITICAL REQUIREMENTS:**

1. **Include EVERYTHING:** Do not summarize or condense the findings from Phase 1 agents. Include all data points, statistics, and details.

2. **Preserve Analysis Depth:** Include complete analysis from all Phase 2 agents without reduction.

3. **Proper Formatting:**
   - Use markdown headers (##, ###, ####)
   - Use bullet points and numbered lists appropriately
   - Bold key terms and statistics
   - Include data tables where appropriate

4. **Length Target:** This should be a comprehensive report of 8,000-12,000 words minimum.

5. **Integration:** While each section preserves its source content, ensure smooth transitions between sections.

6. **Citations:** Maintain all source citations from original research.

7. **Professional Quality:** This is a professional market research report worthy of executive presentation.

**DO NOT:**
- Summarize or condense detailed findings
- Skip any agent's contributions
- Remove data points or statistics
- Create a brief overview instead of comprehensive report

This is THE master document that contains everything. Be thorough and comprehensive.
         """,
         use_llm='google'
      ),
      Agent(
         name="conclusion_writer",
         system_prompt="""
You are a Conclusions & Recommendations Specialist.

Based on the comprehensive report, create a powerful conclusion section:

**20. CONCLUSION & KEY TAKEAWAYS**

1. **Summary of Key Findings (5-7 paragraphs):**
   - Synthesize the most important discoveries
   - Industry health and trajectory
   - Competitive dynamics
   - Market opportunities
   - Critical challenges

2. **Critical Insights (8-10 bullet points):**
   - Most impactful insights from the research
   - Non-obvious discoveries
   - Strategic implications
   - What this means for different stakeholders

3. **Major Implications:**
   - For industry incumbents
   - For new entrants
   - For investors
   - For service providers
   - For customers

4. **Forward-Looking Perspective (2-3 paragraphs):**
   - Where is the industry heading?
   - What are the game-changers?
   - Timeline of expected changes

**21. STRATEGIC RECOMMENDATIONS SUMMARY**

1. **Immediate Actions (0-6 months):**
   - Top 5 priority actions
   - Quick wins
   - Critical must-dos

2. **Short-Term Strategy (6-18 months):**
   - 5-7 key initiatives
   - Building blocks for growth
   - Capability development

3. **Medium-Term Strategy (18-36 months):**
   - 5-7 strategic moves
   - Market positioning
   - Competitive advantages

4. **Long-Term Vision (3-5 years):**
   - Strategic direction
   - Transformation goals
   - Industry leadership positioning

5. **Implementation Considerations:**
   - Resource requirements
   - Key success factors
   - Risks to manage
   - Metrics to track

**Format:** 1,000-1,500 words
**Tone:** Decisive, actionable, insightful
**Goal:** Leave readers with clear understanding and direction
         """,
         use_llm='google'
      ),
      Agent(
         name="quality_reviewer",
         system_prompt="""
You are a Quality Assurance & Report Review Specialist.

Review the comprehensive report for:

1. **Completeness Check:**
   - Verify all sections are present
   - Confirm all agent contributions included
   - Check for missing data or analysis

2. **Quality Assessment:**
   - Data accuracy and consistency
   - Logical flow and structure
   - Clarity and readability
   - Professional presentation

3. **Formatting Review:**
   - Consistent heading styles
   - Proper markdown usage
   - Table formatting
   - Citation consistency

4. **Content Enhancement:**
   - Add transitional paragraphs where needed
   - Enhance readability
   - Improve structure if needed
   - Add cross-references

5. **Final Polish:**
   - Grammar and style
   - Professional language
   - Executive readiness

**Output:** The final, polished, comprehensive report ready for delivery.

If any sections are incomplete or missing, flag them clearly and indicate what needs to be added.
         """,
         use_llm='google'
      ),
      Agent(
         name="formatter",
         system_prompt="""
You are a Document Formatting Specialist.

Apply final professional formatting to the report:

1. **Document Structure:**
   - Proper header hierarchy
   - Consistent spacing
   - Page break markers (if needed)
   - Table of contents links

2. **Visual Enhancement:**
   - Emphasize key statistics (bold)
   - Highlight critical findings
   - Use formatting for readability
   - Create visual separation between sections

3. **Professional Presentation:**
   - Title page formatting
   - Section numbering
   - Footer/header suggestions
   - Professional styling

4. **Final Quality Check:**
   - No formatting errors
   - Consistent style throughout
   - Professional appearance
   - Executive-ready presentation

**Output:** The final formatted comprehensive market research report.

This is the FINAL deliverable - make it exceptional.
            """,
            use_llm='google'
      )
   ]

   for agent in report_agents:
      await agent.configure()

   # Create crews:
   data_crew = AgentCrew(name="DataGathering", agents=data_agents)
   analysis_crew = AgentCrew(name="Analysis", agents=analysis_agents)

   # SWOT and Trend run in parallel on raw data
   # Risk and Opportunity run in parallel after SWOT
   # Strategic synthesizer waits for all analysis
   analysis_crew.task_flow(swot_analyzer, [risk_analyzer, opportunity_analyzer])
   analysis_crew.task_flow(
      [
         swot_analyzer, market_analyzer, new_player_analyzer,
         trend_analyzer, risk_analyzer, opportunity_analyzer
      ],
      strategic_synthesizer
   )

   report_crew = AgentCrew(name="ReportGeneration", agents=report_agents)

   return data_crew, analysis_crew, report_crew

async def execute_workflow(data_crew, analysis_crew, report_crew, industry):
   data_result: CrewResult = await data_crew.run_parallel(
      tasks=[
         {'agent_id': 'industry_overview', 'query': f'Provide an overview of {industry}'},
         {'agent_id': 'market_data', 'query': f'Research {industry}'},
         {'agent_id': 'major_markets', 'query': f'Identify major markets in {industry}'},
         {'agent_id': 'competitor_data', 'query': f'Research competitors in {industry}'},
         {'agent_id': 'distribution_channel', 'query': f'Analyze distribution channels in {industry}'},
         {'agent_id': 'financial_data', 'query': f'Get financial data for {industry}'},
         {'agent_id': 'supply_demand_data', 'query': f'Analyze supply and demand for {industry}'},
         {'agent_id': 'key_statistics', 'query': f'Provide me the key statistics of {industry}'},
         {'agent_id': 'key_statistics_business', 'query': f'Provide me the number of businesses in {industry}'},
         {'agent_id': 'cost_structure', 'query': f'Analyze cost structure in {industry}'},
         {'agent_id': 'industry_revenue', 'query': f'Analyze industry revenue in {industry}'},
         {'agent_id': 'similar_industries', 'query': f'Research similar industries to {industry}'},
         {'agent_id': 'industry_structure', 'query': f'Analyze the industry structure of {industry}'},
         {'agent_id': 'external_drivers', 'query': f'Identify external drivers impacting {industry}'},
         {'agent_id': 'new_players', 'query': f'Research new players in {industry}'},
      ],
      all_results=True
   )
   print(
      f"✓ Phase 1 complete: {len(data_result['results'])} datasets gathered\n"
   )
   # data_result.output is a list of results from each agent
   market_research = '\n'.join(data_result.output)
   print(market_research)

   # Phase 2: Flow-based analysis with dependencies
   print("Phase 2: Flow-Based Analysis")
   print("-" * 50)
   # Create comprehensive context for analysis
   analysis_context = f"""
# COMPREHENSIVE INDUSTRY DATA FOR ANALYSIS: {industry}

## DATA GATHERING RESULTS:

"""
   for agent_name, result in data_result['results'].items():
      analysis_context += f"\n### {agent_name.upper().replace('_', ' ')} DATA:\n{result}\n\n---\n"

   analysis_result: CrewResult = await analysis_crew.run_flow(
      initial_task=analysis_context
   )

   print("✓ Phase 2 complete: Strategic insights generated\n")
   market_analysis = analysis_result.output
   print(market_analysis)

   # Phase 3: Sequential refinement
   print("Phase 3: Sequential Report Refinement")
   print("-" * 50)

   # Create comprehensive report context including BOTH data and analysis
   report_context = f"""
# COMPREHENSIVE MARKET RESEARCH REPORT COMPILATION
## Industry: {industry}

You are compiling a comprehensive market research report that includes:
- All data gathering findings from Phase 1
- All strategic analysis from Phase 2
- Executive summary and conclusions

---

## PART 1: ALL DATA GATHERING RESULTS

"""
   # Include all Phase 1 data
   for result in data_result.output:
      report_context += f"\n### COMPLETE FINDINGS:\n{result}\n\n---\n"

   report_context += """

---

## PART 2: ALL STRATEGIC ANALYSIS RESULTS

"""
   # Include all Phase 2 analysis
   report_context += f"\n{market_analysis}\n\n---\n"

   report_context += """

---

## YOUR MISSION:

Create the comprehensive market research report following the exact structure provided in your system prompt.

This is the master comprehensive Executive report document.

"""

   report_result = await report_crew.run_sequential(
      query=report_context,
      max_tokens=8192,
      model='gemini-2.5-pro',
      pass_full_context=True
   )

   print("✓ Phase 3 complete: Final report ready\n")

   print("\n" + "="*70)
   print("HYBRID WORKFLOW COMPLETE")
   print("="*70)
   print(f"\nPhase 1 (Parallel): {data_result['total_execution_time']:.2f}s")
   print("Phase 2 (Flow): Multiple stages with auto-parallelization")
   print("Phase 3 (Sequential): Pipeline refinement")
   print(f"\nFinal Report (first 400 chars):\n{report_result['final_result'][:400]}...")
   print("\n" + "="*70)

   return {
      'data_results': data_result,
      'analysis_results': analysis_result,
      'final_report': report_result,
      'market_research': market_research,
      'market_analysis': market_analysis
   }

if __name__ == "__main__":
   industry = "Vending Machines (Retail automation) Industry in the US market"
   data_crew, analysis_crew, report_crew = asyncio.run(
      generating_crews()
   )

   result = asyncio.run(
      execute_workflow(data_crew, analysis_crew, report_crew, industry)
   )
   final_report = result.get('final_report', {}).output
   market_research = result.get('market_research', '')
   market_analysis = result.get('market_analysis', '')
   print(final_report)
   # extract one agent from report_crew:
   agent = Agent()
   # generate a PDF from output:
   # asyncio.run(
   #    agent.pdf_report(
   #       content=final_report,
   #       title=f"Market Research Report - {industry}",
   #       author="Automated Research System",
   #       filename="market_research_report.pdf"
   #    )
   # )
   # saving as markdown files:
   asyncio.run(
      agent.markdown_report(
            content=market_analysis,
            title=f"Market Analysis Report - {industry}",
            author="Automated Research System",
            filename="market_analysis_report.md"
      )
   )
   asyncio.run(
      agent.markdown_report(
            content=market_research,
            title=f"Market Research Report - {industry}",
            author="Automated Research System",
            filename="market_research_report.md"
      )
   )
   # Final Report
   asyncio.run(
      agent.markdown_report(
            content=final_report,
            title=f"Final Comprehensive Market Research Report - {industry}",
            author="Automated Research System",
            filename="final_comprehensive_market_research_report.md"
      )
   )
