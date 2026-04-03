"""Example: Agent with CreateFormTool for serving HTML5 forms via natural language.

This example demonstrates how to build an Agent that:
1. Accepts a natural language prompt describing a form
2. Uses CreateFormTool to generate a validated FormSchema via LLM
3. Renders the FormSchema as an HTML5 form fragment
4. Optionally validates submitted data against the schema

Usage:
    source .venv/bin/activate
    python examples/forms/form_agent.py
"""

import asyncio

from parrot.bots import BasicAgent
from parrot.forms import (
    CreateFormTool,
    FormRegistry,
    FormSchema,
    FormValidator,
    StyleSchema,
)
from parrot.forms.renderers.html5 import HTML5Renderer
from parrot.forms.style import LayoutType
from parrot.models.google import GoogleModel


class FormAgent(BasicAgent):
    """An Agent that creates and serves HTML5 forms from natural language prompts.

    Extends BasicAgent with:
    - CreateFormTool: generates FormSchema from a prompt via LLM
    - HTML5Renderer: renders FormSchema as an HTML5 <form> fragment
    - FormValidator: validates user submissions against the schema
    """

    def __init__(self, **kwargs):
        self.registry = FormRegistry()
        self.renderer = HTML5Renderer()
        self.validator = FormValidator()
        super().__init__(
            name="FormAgent",
            agent_id="form-agent",
            **kwargs,
        )

    def agent_tools(self):
        """Register the CreateFormTool so the Agent can generate forms."""
        create_form = CreateFormTool(
            client=self._llm,
            registry=self.registry,
            model=GoogleModel.GEMINI_3_FLASH_LITE_PREVIEW.value,
        )
        return [create_form]

    async def create_and_render_form(
        self,
        prompt: str,
        layout: LayoutType = LayoutType.SINGLE_COLUMN,
        locale: str = "en",
        persist: bool = False,
    ) -> tuple[FormSchema, str]:
        """Create a form from a natural language prompt and render it as HTML5.

        Args:
            prompt: Natural language description of the desired form.
            layout: Layout style for rendering (single_column, two_column, etc.).
            locale: Locale for i18n label resolution.
            persist: Whether to save the form in the registry.

        Returns:
            Tuple of (FormSchema, HTML string).
        """
        # Use the CreateFormTool directly
        create_tool = self.tool_manager.get_tool("create_form")
        result = await create_tool.execute(
            prompt=prompt,
            persist=persist,
        )

        if not result.success:
            error = result.metadata.get("error", "Unknown error")
            raise RuntimeError(f"Form creation failed: {error}")

        form = FormSchema.model_validate(result.metadata["form"])

        # Render as HTML5
        style = StyleSchema(layout=layout)
        rendered = await self.renderer.render(form, style=style, locale=locale)
        return form, rendered.content

    async def validate_submission(
        self,
        form: FormSchema,
        data: dict,
        locale: str = "en",
    ) -> dict:
        """Validate form submission data against the schema.

        Args:
            form: The FormSchema to validate against.
            data: Submitted form data (field_id -> value).
            locale: Locale for error messages.

        Returns:
            Dict with 'is_valid', 'errors', and 'sanitized_data' keys.
        """
        result = await self.validator.validate(form, data, locale=locale)
        return {
            "is_valid": result.is_valid,
            "errors": result.errors,
            "sanitized_data": result.sanitized_data if result.is_valid else {},
        }

    async def render_with_errors(
        self,
        form: FormSchema,
        data: dict,
        errors: dict[str, str],
        locale: str = "en",
    ) -> str:
        """Re-render a form with pre-filled data and validation errors.

        Args:
            form: The FormSchema to render.
            data: Previously submitted data to pre-fill.
            errors: Field-level error messages.
            locale: Locale for i18n.

        Returns:
            HTML string with errors displayed inline.
        """
        rendered = await self.renderer.render(
            form,
            locale=locale,
            prefilled=data,
            errors=errors,
        )
        return rendered.content


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

async def main():
    agent = FormAgent()
    await agent.configure()

    # 1. Create a customer feedback form from natural language
    print("--- Creating a customer feedback form ---\n")
    form, html = await agent.create_and_render_form(
        prompt=(
            "Create a customer feedback form with: "
            "full name (required), email (required), "
            "satisfaction rating from 1 to 5, "
            "product category dropdown (Electronics, Clothing, Food, Other), "
            "and a comments text area"
        ),
        layout=LayoutType.SINGLE_COLUMN,
        persist=True,
    )
    print(f"Form ID: {form.form_id}")
    print(f"Title:   {form.title}")
    print(f"Fields:  {len([f for s in form.sections for f in s.fields])}")
    print(f"\nHTML output ({len(html)} chars):\n")
    print(html[:500], "...\n" if len(html) > 500 else "\n")

    # 2. Simulate validating a submission
    print("--- Validating a submission ---\n")
    submission = {
        "full_name": "Jane Doe",
        "email": "jane@example.com",
        "satisfaction_rating": 4,
        "product_category": "Electronics",
        "comments": "Great product, fast shipping!",
    }
    validation = await agent.validate_submission(form, submission)
    print(f"Valid: {validation['is_valid']}")
    if validation["errors"]:
        print(f"Errors: {validation['errors']}")
    else:
        print(f"Sanitized data: {validation['sanitized_data']}")

    # 3. Simulate an invalid submission and re-render with errors
    print("\n--- Invalid submission with re-render ---\n")
    bad_submission = {
        "full_name": "",
        "email": "not-an-email",
        "comments": "Missing required fields!",
    }
    bad_validation = await agent.validate_submission(form, bad_submission)
    if not bad_validation["is_valid"]:
        print(f"Errors: {bad_validation['errors']}")
        error_html = await agent.render_with_errors(
            form, bad_submission, bad_validation["errors"]
        )
        print(f"\nRe-rendered HTML with errors ({len(error_html)} chars)")

    # 4. Refine the form with a follow-up prompt
    print("\n--- Refining the form ---\n")
    create_tool = agent.tool_manager.get_tool("create_form")
    refine_result = await create_tool.execute(
        prompt="Add a phone number field and make the rating field required",
        refine_form_id=form.form_id,
    )
    if refine_result.success:
        refined = FormSchema.model_validate(refine_result.metadata["form"])
        print(f"Refined form has {len([f for s in refined.sections for f in s.fields])} fields")
        _, refined_html = await agent.create_and_render_form(
            prompt="Add a phone number field and make the rating field required",
            persist=True,
        )
        print(f"Refined HTML: {len(refined_html)} chars")


if __name__ == "__main__":
    asyncio.run(main())
