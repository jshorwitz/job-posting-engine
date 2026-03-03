#!/usr/bin/env python3
"""
Generate branded images for LinkedIn posts using Google Imagen via the Gemini API.

Usage:
    # As a module
    from engine.x.generate_linkedin_image import generate_image
    image_path = generate_image(
        prompt="Modern dark dashboard showing cross-platform ad analytics...",
        output_dir="data/linkedin-images",
        filename="week1_post1.png",
    )

    # As CLI
    python -m engine.x.generate_linkedin_image \
        --prompt "Dark tech visualization..." \
        --output data/linkedin-images/test.png

    # Batch mode
    python -m engine.x.generate_linkedin_image \
        --batch posts.json \
        --output-dir data/linkedin-images

Auth: GEMINI_API_KEY environment variable.
Output: 1200x627 PNG (LinkedIn recommended image size).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import httpx

IMAGEN_MODEL = "imagen-4.0-generate-001"
REST_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGEN_MODEL}:predict"
)

BRAND_SUFFIX = """
Brand styling requirements:
- Dark background #0B0E12
- Primary accent color: lime green #9CFF5A
- Secondary accent: cyan #4DD6FF
- Modern, clean, minimal tech aesthetic
- CRITICAL: Do NOT include any text, words, letters, logos, or brand names in the image. The image must be purely visual/abstract with no typography whatsoever.
- CRITICAL: Do NOT attempt to render company logos (Google, Meta, LinkedIn, etc.). Use abstract geometric shapes, nodes, or glowing circles instead.
- Professional, high-contrast, suitable for B2B audience
- Abstract data visualization style preferred
""".strip()


def _replace_hex_codes(prompt: str) -> str:
    """Replace hex color codes with color names to prevent Imagen from rendering them as text."""
    # Map Synter brand hex codes to descriptive color names
    replacements = {
        "#0B0E12": "very dark charcoal",
        "#9CFF5A": "bright lime green",
        "#4DD6FF": "bright cyan blue",
        "#E4453A": "vivid red",
        "#3EE08F": "bright emerald green",
        "#E6E9EF": "off-white",
        "#B8C0CC": "light gray",
        "#2A303A": "dark gray",
    }
    for hex_code, name in replacements.items():
        prompt = prompt.replace(f"({hex_code})", f"({name})")
        prompt = prompt.replace(hex_code, name)
        prompt = prompt.replace(hex_code.lower(), name)
    # Catch any remaining hex codes
    import re
    prompt = re.sub(r'\(#[0-9A-Fa-f]{6}\)', '', prompt)
    prompt = re.sub(r'#[0-9A-Fa-f]{6}\b', '', prompt)
    return prompt


def _enhance_prompt(prompt: str) -> str:
    """Append Synter brand guidelines to the user prompt, stripping hex codes to prevent text rendering."""
    combined = f"{prompt.strip()}\n\n{BRAND_SUFFIX}"
    return _replace_hex_codes(combined)


def _generate_via_sdk(prompt: str) -> bytes:
    """Generate an image using the google-genai Python SDK."""
    from google import genai  # type: ignore[import-untyped]
    from google.genai import types  # type: ignore[import-untyped]

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_images(
        model=IMAGEN_MODEL,
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="16:9",
            safety_filter_level="BLOCK_LOW_AND_ABOVE",
        ),
    )
    if not response.generated_images:
        raise RuntimeError("Imagen returned no images — prompt may have been blocked by safety filters")
    return response.generated_images[0].image.image_bytes  # type: ignore[return-value]


def _generate_via_rest(prompt: str) -> bytes:
    """Fallback: call the Gemini REST API directly."""
    api_key = os.environ["GEMINI_API_KEY"]
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "16:9"},
    }
    resp = httpx.post(
        REST_URL,
        params={"key": api_key},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    predictions = data.get("predictions")
    if not predictions:
        raise RuntimeError(
            f"Imagen REST API returned no predictions: {json.dumps(data, indent=2)}"
        )
    b64 = predictions[0].get("bytesBase64Encoded")
    if not b64:
        raise RuntimeError("No image bytes in REST response")
    return base64.b64decode(b64)


def _generate_image_bytes(prompt: str) -> bytes:
    """Generate image bytes, trying the SDK first then falling back to REST."""
    enhanced = _enhance_prompt(prompt)
    try:
        return _generate_via_sdk(enhanced)
    except ImportError:
        return _generate_via_rest(enhanced)


def generate_image(
    prompt: str,
    output_dir: str = "data/linkedin-images",
    filename: str = "image.png",
) -> str:
    """Generate a single branded LinkedIn image and save it as PNG.

    Returns the absolute path to the saved file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / filename

    image_bytes = _generate_image_bytes(prompt)
    dest.write_bytes(image_bytes)
    return str(dest.resolve())


def generate_batch(
    posts: list[dict[str, str]],
    output_dir: str = "data/linkedin-images",
) -> list[dict[str, str]]:
    """Generate images for multiple posts.

    Each entry in *posts* should have at least ``prompt`` and ``filename`` keys.
    Returns a list of result dicts with ``filename``, ``path``, and ``status``.
    """
    results: list[dict[str, str]] = []
    for post in posts:
        prompt = post.get("prompt", "")
        filename = post.get("filename", "image.png")
        try:
            path = generate_image(prompt, output_dir=output_dir, filename=filename)
            results.append({"filename": filename, "path": path, "status": "ok"})
        except Exception as exc:
            results.append({"filename": filename, "path": "", "status": f"error: {exc}"})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate branded LinkedIn images via Google Imagen",
    )
    parser.add_argument("--prompt", help="Image generation prompt")
    parser.add_argument("--output", help="Output file path (e.g. data/img.png)")
    parser.add_argument("--batch", help="JSON file with list of {prompt, filename} objects")
    parser.add_argument("--output-dir", default="data/linkedin-images", help="Directory for batch output")
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        print(json.dumps({"success": False, "error": "GEMINI_API_KEY not set"}))
        sys.exit(1)

    if args.batch:
        batch_path = Path(args.batch)
        if not batch_path.exists():
            print(json.dumps({"success": False, "error": f"Batch file not found: {args.batch}"}))
            sys.exit(1)
        posts = json.loads(batch_path.read_text())
        results = generate_batch(posts, output_dir=args.output_dir)
        print(json.dumps({"success": True, "results": results}, indent=2))
        return

    if not args.prompt:
        parser.error("--prompt is required (or use --batch)")

    output = args.output or os.path.join(args.output_dir, "image.png")
    out_path = Path(output)
    try:
        path = generate_image(args.prompt, output_dir=str(out_path.parent), filename=out_path.name)
        print(json.dumps({"success": True, "path": path}))
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
