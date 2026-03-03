#!/usr/bin/env python3
"""Publish posts to the SynterAI LinkedIn organization page.

Supports text-only posts and posts with images via the LinkedIn REST API v202510.

Reuses token refresh and cache logic from linkedin_crosspost.py.
"""

import argparse
import json
import os
import sys
import functools
from pathlib import Path

import requests

from engine.x.linkedin_crosspost import (
    get_linkedin_auth,
    _retry_with_refresh,
    _refresh_token,
    _save_token_cache,
    LINKEDIN_TOKEN_CACHE,
)

ORG_URN = "urn:li:organization:4803356"
API_VERSION = "202510"
BASE_URL = "https://api.linkedin.com"


def _rest_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def _upload_image(image_path: str, token: str) -> str:
    """Upload an image and return its URN. Retries once on 401."""
    # 1. Initialize upload
    init_resp = requests.post(
        f"{BASE_URL}/rest/images?action=initializeUpload",
        headers=_rest_headers(token),
        json={"initializeUploadRequest": {"owner": ORG_URN}},
        timeout=30,
    )
    if init_resp.status_code == 401:
        raise requests.HTTPError(response=init_resp)
    init_resp.raise_for_status()
    init_data = init_resp.json()["value"]
    upload_url = init_data["uploadUrl"]
    image_urn = init_data["image"]

    # 2. Binary PUT
    with open(image_path, "rb") as f:
        put_resp = requests.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            data=f,
            timeout=120,
        )
    put_resp.raise_for_status()

    return image_urn


def _create_post(text: str, image_urn: str | None, token: str) -> dict:
    """Create a post on the organization page. Returns the API response info."""
    payload: dict = {
        "author": ORG_URN,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
    }

    if image_urn:
        payload["content"] = {
            "media": {
                "title": "Image",
                "id": image_urn,
            }
        }

    resp = requests.post(
        f"{BASE_URL}/rest/posts",
        headers=_rest_headers(token),
        json=payload,
        timeout=30,
    )
    if resp.status_code == 401:
        raise requests.HTTPError(response=resp)
    resp.raise_for_status()

    post_urn = resp.headers.get("x-restli-id", "")
    url = f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else ""
    return {"success": True, "post_urn": post_urn, "url": url}


def _do_post(token: str, text: str, image_path: str | None) -> dict:
    """Internal: upload image (if any) and create post. Returns result dict."""
    try:
        image_urn = None
        if image_path:
            image_urn = _upload_image(image_path, token)

        return _create_post(text, image_urn, token)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        error_body = ""
        if exc.response is not None:
            try:
                error_body = exc.response.json()
            except ValueError:
                error_body = exc.response.text[:500]
        return {
            "success": False,
            "error": f"401: LinkedIn token expired" if status == 401 else str(exc),
            "status_code": status,
            "details": error_body,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def post_to_linkedin_native(text: str, image_path: str = None) -> dict:
    """Post to the SynterAI LinkedIn org page (importable entry point).

    Args:
        text: Post body text (up to 3000 chars).
        image_path: Optional path to an image file to attach.

    Returns:
        dict with success, post_urn, url on success; success, error on failure.
    """
    if image_path and not Path(image_path).is_file():
        return {"success": False, "error": f"Image not found: {image_path}"}

    try:
        token, _org_urn = get_linkedin_auth()
    except Exception as exc:
        return {"success": False, "error": f"Token error: {exc}"}

    return _retry_with_refresh(_do_post, token, text, image_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish a post to the SynterAI LinkedIn organization page"
    )
    parser.add_argument("--text", required=True, help="Post body text")
    parser.add_argument("--image-path", help="Path to an image file to attach")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without posting"
    )
    args = parser.parse_args()

    if args.image_path and not Path(args.image_path).is_file():
        print(
            json.dumps(
                {"success": False, "error": f"Image not found: {args.image_path}"}
            )
        )
        sys.exit(1)

    if args.dry_run:
        preview: dict = {
            "dry_run": True,
            "author": ORG_URN,
            "text": args.text,
            "has_image": bool(args.image_path),
        }
        if args.image_path:
            preview["image_path"] = args.image_path
        print(json.dumps(preview, indent=2))
        return

    result = post_to_linkedin_native(args.text, args.image_path)
    print(json.dumps(result, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
