#!/usr/bin/env python3
"""Generate branded images for LinkedIn posts using Google Imagen 4."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


BRAND_SUFFIX = (
    " Style: dark background (#0B0E12), lime green accent (#9CFF5A),"
    " cyan accent (#4DD6FF), modern tech-forward aesthetic,"
    " clean minimal composition. Do NOT include any text or lettering."
)


def get_output_dir() -> Path:
    if os.path.isdir("/data"):
        d = Path("/data/linkedin_images")
    else:
        d = Path(__file__).parent / "linkedin_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_image(prompt: str, output_name: str = None, no_brand: bool = False) -> dict:
    """Generate a branded LinkedIn image.

    Args:
        prompt: Image generation prompt.
        output_name: Output filename without extension (auto-generated if None).
        no_brand: If True, skip Synter brand suffix injection.

    Returns:
        dict with keys: success, image_path, prompt_used (on success)
              or: success, error (on failure).
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"success": False, "error": "GEMINI_API_KEY environment variable not set"}

    enhanced_prompt = prompt if no_brand else prompt + BRAND_SUFFIX
    output_name = output_name or f"linkedin_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_path = get_output_dir() / f"{output_name}.png"

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_images(
            model="imagen-4.0-generate-001",
            prompt=enhanced_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                safety_filter_level="BLOCK_LOW_AND_ABOVE",
                aspect_ratio="16:9",
            ),
        )

        if not response.generated_images:
            return {"success": False, "error": "No images generated — prompt may have been blocked by safety filters"}

        output_path.write_bytes(response.generated_images[0].image.image_bytes)

        return {
            "success": True,
            "image_path": str(output_path),
            "prompt_used": enhanced_prompt,
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description="Generate LinkedIn images with Imagen 4")
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--output-name", default=None, help="Output filename (without extension)")
    parser.add_argument("--no-brand", action="store_true", help="Skip Synter brand injection")
    args = parser.parse_args()

    result = generate_image(prompt=args.prompt, output_name=args.output_name, no_brand=args.no_brand)
    print(json.dumps(result))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
