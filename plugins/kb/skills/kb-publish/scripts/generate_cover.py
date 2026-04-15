#!/usr/bin/env python3
"""Generate podcast cover art via Google Gemini (Nano Banana) image generation."""

import argparse
import os
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(description="Generate cover art via Gemini API")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="Image generation prompt (inline)")
    group.add_argument("--prompt-file", help="Path to file containing the prompt")
    parser.add_argument("--output", required=True, help="Output file path (PNG)")
    parser.add_argument("--model", default="gemini-2.5-flash-image", help="Gemini model name")
    parser.add_argument("--aspect", default="1:1", help="Aspect ratio (e.g., 1:1, 16:9)")
    return parser.parse_args()


def generate_image(client, model, prompt, aspect):
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect),
        ),
    )

    for part in response.parts:
        if part.inline_data is not None:
            return part.as_image()

    raise RuntimeError("No image data in Gemini response")


def main():
    args = parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    from google import genai

    client = genai.Client(api_key=api_key)

    prompt = args.prompt
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read().strip()

    last_error = None
    for attempt in range(2):
        try:
            image = generate_image(client, args.model, prompt, args.aspect)
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            image.save(args.output)
            print(f"Cover saved to {args.output}", file=sys.stderr)
            sys.exit(0)
        except Exception as e:
            last_error = e
            if attempt == 0:
                print(f"Attempt 1 failed: {e}. Retrying in 5s...", file=sys.stderr)
                time.sleep(5)

    print(f"Failed after 2 attempts: {last_error}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
