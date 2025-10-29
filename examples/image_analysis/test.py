import asyncio
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from navconfig import BASE_DIR
from parrot.clients.google import GoogleGenAIClient, GoogleModel


class ImageAnalysisResult(BaseModel):
    """Represents the result of an image analysis operation."""
    request_date: str = Field(None, description="Date when the analysis was requested")
    vendor_invoice_nbr: Optional[str] = Field(None, description="Vendor invoice number if detected")
    sap_reference_nbr: Optional[str] = Field(None, description="SAP reference number if detected")


async def extract_sap_reference(image_path: str) -> Any:
    """
    Analyze the image at the given path to extract SAP reference number and vendor invoice number.

    Args:
        image_path (str): Path to the image file.

    Returns:
        ImageAnalysisResult: The result of the image analysis.
    """
    # Simulate image analysis
    async with GoogleGenAIClient() as client:
        analysis_prompt = (
            """Analyze the image and extract the Request Date, SAP reference number and vendor invoice number.
            If any of these fields are not found, return null for that field.
Identify the following fields:
* Request Date:
* SAP Reference Nbr:
* Vendor Invoice Nbr:
Return the results in JSON format with fields 'sap_reference_nbr' and 'vendor_invoice_nbr'.
            """
        )
        response = await client.ask_to_image(
            prompt=analysis_prompt,
            model=GoogleModel.GEMINI_2_5_PRO,
            image=image_path,
            structured_output=ImageAnalysisResult
        )
        return response.output or None

if __name__ == "__main__":
    image_path = BASE_DIR / "examples" / "image_analysis" / "image.jpeg"
    result = asyncio.run(extract_sap_reference(image_path))
    print(result)
