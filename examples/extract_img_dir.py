from PIL import Image
import json
from paddleocr import PaddleOCR
import pytesseract
from transformers import (
    LayoutLMv3Processor,
    LayoutLMv3ForTokenClassification,
)
import torch
from navconfig import BASE_DIR

def normalize_bbox(bbox, width, height):
    return [
        int(1000 * (bbox[0] / width)),   # left
        int(1000 * (bbox[1] / height)),  # top
        int(1000 * (bbox[2] / width)),   # right
        int(1000 * (bbox[3] / height))   # bottom
    ]

def using_layoutml(image_path, crop_area=None):
    """
    Extracts structured information from a directory of people using LayoutLMv3.

    Args:
        image_path (str): Path to the screenshot image.

    Returns:
        Dict: Structured data extracted from the image.
    """
    # Initialize the processor and model
    processor = LayoutLMv3Processor.from_pretrained("microsoft/layoutlmv3-base", apply_ocr=False)
    model = LayoutLMv3ForTokenClassification.from_pretrained("microsoft/layoutlmv3-base", num_labels=2)

    # Open the image
    image = Image.open(image_path).convert("RGB")
    image_width, image_height = image.size

    # Crop the image if a crop area is provided
    if crop_area:
        # Crop the image to the specified area
        image = image.crop(crop_area)

    # Use pytesseract to extract the text with bounding boxes
    ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    texts = ocr_data['text']
    boxes = list(zip(ocr_data['left'], ocr_data['top'],
                 ocr_data['width'], ocr_data['height']))

    # Filter out empty texts
    filtered_texts_boxes = [
        (text, (left, top, left+width, top+height)) for text, left, top, width, height in zip(
            ocr_data['text'], ocr_data['left'], ocr_data['top'], ocr_data['width'], ocr_data['height']
        ) if text.strip()
    ]

    # Prepare the input for the model
    texts, bounding_boxes = zip(*filtered_texts_boxes)
    normalized_boxes = [
        normalize_bbox(box, image_width, image_height) for box in bounding_boxes
    ]

    if len(texts) != len(normalized_boxes):
        raise ValueError("Mismatch between number of texts and bounding boxes.")

    encoded_inputs = processor(
        images=image,
        text=list(texts),
        boxes=list(normalized_boxes),
        return_tensors="pt",
        truncation=True,
        padding=True
    )
    # Forward pass through the model
    outputs = model(**encoded_inputs)

    # Get predicted labels
    predicted_labels = torch.argmax(outputs.logits, dim=-1)

    extracted_data = []
    for i, label in enumerate(predicted_labels[0]):
        # Ensure the index does not go out of bounds
        if i < len(texts):
            extracted_data.append({
                "text": texts[i],  # Original text
                "bounding_box": normalized_boxes[i],  # Corresponding bounding box
                "label": int(label.item())  # Convert label tensor to int for JSON serialization
            })

    # Convert the result to JSON
    json_output = json.dumps(extracted_data, indent=2)

    # Print or save the JSON output
    print(json_output)

    return json.loads(json_output)


def using_ocr(image_path):
    """
    Extracts information from a screenshot containing a directory of people using PaddleOCR.
    Args:
        image_path (str): Path to the screenshot image.
    Returns:
        List[Dict]: A list of dictionaries containing extracted text and their positions.
    """
    # Initialize PaddleOCR with English language support
    ocr = PaddleOCR(use_angle_cls=True, lang='en')  # Enable angle classifier for rotated text

    # Perform OCR on the image
    ocr_result = ocr.ocr(str(image_path), cls=True)

    # Process OCR results to reconstruct paragraphs
    paragraphs = []
    current_paragraph = {
        "text": "",
        "bounding_boxes": [],
        "confidence_scores": []
    }

    # Iterate through the detected lines
    for line in ocr_result[0]:  # ocr_result[0] contains the OCR results for the image
        if isinstance(line, list) and len(line) > 0:  # Ensure the line contains valid data
            try:
                # Extract text, confidence, and bounding boxes
                line_text = " ".join([word_info[1][0] for word_info in line if isinstance(word_info, list)])  # Combine words
                confidence = sum([word_info[1][1] for word_info in line if isinstance(word_info, list)]) / len(line)
                bounding_boxes = [word_info[0] for word_info in line if isinstance(word_info, list)]  # Extract bounding boxes

                # Add the line to the current paragraph
                if current_paragraph["text"]:  # If paragraph already contains text, add a line break
                    current_paragraph["text"] += "\n"
                current_paragraph["text"] += line_text
                current_paragraph["bounding_boxes"].extend(bounding_boxes)
                current_paragraph["confidence_scores"].append(confidence)
            except Exception as e:
                print(f"Error processing line: {line} - {e}")
                continue

    # Add the final paragraph to the list
    if current_paragraph["text"]:
        paragraphs.append({
            "text": current_paragraph["text"],
            "bounding_boxes": current_paragraph["bounding_boxes"],
            "confidence": sum(current_paragraph["confidence_scores"]) / len(current_paragraph["confidence_scores"])
        })

    return paragraphs

def main():
    # Path to the screenshot image
    image_path = BASE_DIR.joinpath('documents', 'photo_2024-12-04_15-13-51.jpg')

    # Extract information using PaddleOCR
    paragraphs = using_ocr(image_path)

    # Print reconstructed paragraphs
    for paragraph in paragraphs:
        print(
            f"Paragraph:\n{paragraph['text']}\nConfidence: {paragraph['confidence']:.2f}"
        )

    crop_area = (0, 200, 1080, 1800)  # Example: Skip phone bar and footer
    entities = using_layoutml(image_path, crop_area)

    print(entities)
    # # Display the extracted entities
    # for entity in entities:
    #     print(f"{entity['label']}: {entity['text']}")

if __name__ == "__main__":
    main()
