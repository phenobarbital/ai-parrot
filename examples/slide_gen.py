import asyncio
from parrot.bots import BasicBot
from parrot.llms.vertex import VertexLLM


summary = """
**Executive Summary:**

Analysis of the visit data reveals key trends in store visits, visitor activity, and frequently asked questions. The Vitamin Shoppe TVS0003 Harwood Heights IL is the most visited store, while Velastegui, Irving is the most frequent visitor.  Understanding customer interaction trends and product availability is crucial for optimizing resource allocation and improving sales performance.  Outliers in visit frequency and product sampling require further investigation to mitigate potential risks.

**Key Trends:**

* **Store Visits:** The Vitamin Shoppe TVS0003 Harwood Heights IL leads in visit frequency with 168 visits, significantly higher than other locations.  This suggests potential regional variations in customer engagement or marketing effectiveness.  The top 10 most visited stores account for a substantial portion of overall visits, indicating potential focus areas for resource allocation.

* **Visitor Activity:** Velastegui, Irving conducted the most visits (2921), significantly more than other visitors. This high level of engagement could be valuable for gathering feedback and understanding customer needs.

* **Frequently Asked Questions:** The most common question, "How many customers did you interact with today?", appeared 794 times, highlighting the importance of tracking customer interactions.  Other frequent questions relate to product placement, pricing, and promotions, indicating areas for potential process improvement and staff training.

**Outliers:**

* **Unusual Visit Patterns:**  While the average visit length is approximately 50 minutes, some stores exhibit significant variations in visit frequency on specific dates.  Further investigation is needed to determine if these variations are due to promotional events, staffing issues, or other external factors.  For example, some stores have single-day visit counts significantly higher than their average, which warrants further investigation.

* **Product Availability and Sampling:** The 'on_hand' and 'sampling' data show a mean of 0.16 and 0.04 respectively, with maximum values of 12 and 15. These outliers suggest potential inconsistencies in inventory management or sampling practices, requiring further investigation to ensure accurate tracking and efficient resource allocation.

**Potential Risks:**

* **Over-reliance on Top Performers:** The high concentration of visits at specific stores and by specific visitors creates a potential risk of over-reliance.  If these key contributors experience changes in availability or engagement, it could significantly impact overall performance.

* **Inventory Management:** The outliers observed in 'on_hand' and 'sampling' data suggest potential inefficiencies in inventory management and sampling practices.  These inconsistencies could lead to stockouts, lost sales opportunities, or inaccurate demand forecasting.

* **Data Quality:**  The high frequency of the question "How many customers did you interact with today?" may indicate a data collection issue or a lack of clarity in reporting guidelines. This could impact the reliability of customer interaction data.

**Recommendations:**

* **Diversify Engagement:** Explore strategies to increase engagement across a wider range of stores and visitors to reduce reliance on top performers. This could include targeted marketing campaigns, staff training initiatives, or community outreach programs.

* **Optimize Inventory Management:** Implement stricter inventory control measures and standardized sampling procedures to address the observed inconsistencies. This will ensure accurate stock levels, minimize waste, and improve demand forecasting.

* **Review Data Collection Practices:**  Clarify reporting guidelines and provide additional training to ensure the accuracy and consistency of customer interaction data.  Consider implementing automated tracking systems to reduce manual data entry errors.

* **Leverage Top Performers:** Engage with frequent visitors like Velastegui, Irving to gather feedback and insights into customer preferences.  This information can be used to improve product offerings, customer service, and overall store experience.
"""

## Define Bot:
class SlideBot(BasicBot):
    """Slide Creation Bot.
    A Bot for creating Slides to generate presentations, PowerPoint or PDF files.
    """
    name: str = "SlideBot"
    system_prompt_template = """
You are {name}, an expert PowerPoint presentation creator. Create a compelling presentation about the provided "Narrative Output" with exactly 10 slides, using your expertise.

Use the following information as a basis, but feel free to expand on it with your knowledge:
{context}
End of Context.

**IMPORTANT**
Structure the presentation according to the user instructions and the specified number of slides. Always include:
1. An engaging introduction slide
2. A conclusion slide summarizing the main points
3. A "Next Steps" or "Call to Action" slide that includes the contact details if any, !important
4. Return only a valid JSON object with no additional text or markdown formatting.

Adapt the following presentation slides to a corporate style for a marketing and management audience. Mandatory. Maintain the overall structure and key points, but adjust the language, tone, and complexity accordingly.
Adjust the content to fit the specified number of slides. If more slides are requested, expand on the topic with more details. If fewer slides are requested, focus on the most important points and summarize the content accordingly.

Each slide should have:
- A concise, attention-grabbing title
- Points of key information (written in full sentences), elaborate if required
- A picture description that can be used to generate an image using GenAI, describe a picture based on the context of the slide and the main context of the presentation that fits correctly on the topic being discussed, paying special attention to the details of the characters or elements, what they are doing, and how they are placed.
- A brief speaker note providing additional context or talking points.

Encourage creativity and innovation in crafting visually appealing slides, including thoughtful design elements and layouts that enhance the narrative and engage the audience.
Return the adapted slides in the same JSON format. Do NOT HALLUCINATE. Make sure the JSON format is passed. Nothing else, Take a deep breath before starting any task.

# Output Format

Return the structured information as a JSON as follows (return exactly this JSON structure):

```
{{
    "slides": [
        {{
            "num_slides": "slide number from 0 to last slide",
            "title": "Slide Title",
            "content": "Bullet point 1\\n Bullet point 2\\n Bullet point 3",
            "insert_images": "picture description with relation to the bullet points and main theme",
            "speaker_note": "Additional context or talking points for the presenter"
        }},
        // ... more slides ...
    ]
}}

```

# Examples

**Example Slide Format:**

- **Title:** Overview of AI Trends
- **Content:**
  - "AI adoption has increased by 50% in the last year."
  - "Machine learning applications are evolving rapidly."
  - "Ethical considerations are becoming crucial."
- **Insert Images:** "An infographic showing the growth of AI adoption, with graph and data points. Characters discussing AI ethics in a modern meeting room."
- **Speaker Note:** "Highlight the rapid growth and implications of AI in various sectors. Discuss potential challenges with AI ethics."

# Notes

- Ensure the narrative and additional instructions harmonize, focusing on clear, engaging storytelling.
- Think about the balance of text, images, and graphics to maintain audience interest.
- Utilize GenAI effectively for image generation according to the slide context.


"""  # pylint: disable=line-too-long # noqa


async def create_bot():
    # Create a bot instance:
    bot = SlideBot(
        llm=VertexLLM(
            model='gemini-2.0-flash',
            temperature=0.2,
            top_k=30,
            top_p=0.6,
        )
    )
    # configure the bot:
    await bot.configure()
    return bot


if __name__ == "__main__":
    # Run the bot:
    loop = asyncio.get_event_loop()
    bot = loop.run_until_complete(create_bot())
    print('PROMPT')
    print(bot.system_prompt_template)
    # Create a presentation:
    response = loop.run_until_complete(
        bot.question(f"Generate the slides from the following Executive Summary:\n {summary}")
    )
    print('RESULT')
    print(response)
