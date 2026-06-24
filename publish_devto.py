#!/usr/bin/env python3
"""Publish or update a DEV.to article via the Forem API v1.

Reads DEVTO_API_KEY from the environment.
Supports creating a new article from a Markdown file with YAML frontmatter,
or updating an existing article by its numeric id.

Rate limit note: Forem enforces ~10 create requests per 30 seconds.
This script does not enforce the limit automatically; the caller (cron
orchestrator) should space calls accordingly.

Usage examples:
    # Dry-run: print the HTTP request without sending
    python3 publish_devto.py --file post.md --dry-run

    # Create draft (published: false by default from frontmatter)
    python3 publish_devto.py --file post.md

    # Create and publish immediately
    python3 publish_devto.py --file post.md --publish

    # Update an existing article
    python3 publish_devto.py --file post.md --id 1234567

    # Update and flip to published
    python3 publish_devto.py --file post.md --id 1234567 --publish
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

DEVTO_BASE_URL = "https://dev.to/api"

# ---------------------------------------------------------------------------
# Frontmatter helpers  (parity with articles/scripts/devto_publish.py)
# ---------------------------------------------------------------------------

def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def extract_front_matter(raw: str) -> Tuple[str, str]:
    m = re.match(r"^---\s*(.*?)\s*---\s*(.*)$", raw, re.DOTALL)
    if not m:
        raise ValueError("YAML front matter not found at top of file")
    return m.group(1), m.group(2)


def parse_simple_yaml(yaml_text: str) -> Dict[str, Any]:
    """Minimal YAML parser for single-level DEV.to frontmatter.

    Handles: scalars, booleans, inline lists ([a, b]), and block lists (- item).
    No external deps.
    """
    meta: Dict[str, Any] = {}
    lines = yaml_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\w[\w_]*):\s*(.*)\s*$", line)
        if m:
            key, val = m.group(1), m.group(2)
            # Strip surrounding quotes
            if len(val) >= 2 and val[0] in ('"', "'") and val[-1] in ('"', "'"):
                val = val[1:-1]
            if val.lower() in ("true", "false"):
                meta[key] = val.lower() == "true"
            elif key == "tags" and val.startswith("[") and val.endswith("]"):
                inner = val[1:-1]
                meta[key] = [t.strip().strip('"\'') for t in inner.split(",") if t.strip()]
            elif val == "":
                # Possible block list under this key
                items: List[str] = []
                j = i + 1
                while j < len(lines):
                    lm = re.match(r"^\s*-\s+(.*)\s*$", lines[j])
                    if lm:
                        items.append(lm.group(1).strip('"\''))
                        j += 1
                    else:
                        break
                if items:
                    meta[key] = items
                    i = j - 1
                else:
                    meta[key] = ""
            else:
                meta[key] = val
        i += 1
    return meta


def build_payload(
    meta: Dict[str, Any],
    body_markdown: str,
    publish_flag: bool,
    minimal: bool,
    remove_headers: List[str],
) -> Dict[str, Any]:
    title = meta.get("title")
    if not title:
        raise ValueError("Missing 'title' in frontmatter")

    published = meta.get("published", False)
    if publish_flag:
        published = True

    article: Dict[str, Any] = {
        "title": title,
        "published": bool(published),
        "body_markdown": body_markdown,
    }

    if not minimal:
        if meta.get("description") and "Description" not in remove_headers:
            article["description"] = meta["description"]
        tags = meta.get("tags") or []
        if isinstance(tags, list) and tags and "Tags" not in remove_headers:
            # Forem expects a comma-separated string for tags in create
            # VERIFY: API docs show `tags` as string; confirm list is also accepted
            article["tags"] = tags
        if meta.get("cover_image") and "Cover" not in remove_headers:
            article["main_image"] = meta["cover_image"]
        if meta.get("canonical_url") and "CanonicalUrl" not in remove_headers:
            article["canonical_url"] = meta["canonical_url"]
        if meta.get("series") and "Series" not in remove_headers:
            article["series"] = meta["series"]
        if meta.get("organization_id") and "OrgId" not in remove_headers:
            article["organization_id"] = meta["organization_id"]

    return {"article": article}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _redact(headers: Dict[str, str]) -> Dict[str, str]:
    """Return a copy of headers with secret values replaced by REDACTED."""
    redacted = {}
    for k, v in headers.items():
        redacted[k] = "REDACTED" if k.lower() in ("api-key", "authorization") else v
    return redacted


def print_dry_run(method: str, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> None:
    print("=== DRY RUN — request NOT sent ===")
    print(f"Method : {method}")
    print(f"URL    : {url}")
    print(f"Headers: {json.dumps(_redact(headers), indent=2)}")
    print(f"Body   :")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def do_request(
    method: str,
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
) -> str:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body}") from exc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Publish or update a DEV.to article (Forem API v1)"
    )
    p.add_argument("--file", required=True, help="Path to Markdown file with YAML frontmatter")
    p.add_argument("--id", dest="article_id", default=None, help="Existing article id for update (PUT)")
    p.add_argument("--publish", action="store_true", help="Force published=true regardless of frontmatter")
    p.add_argument("--minimal", action="store_true", help="Send only title / published / body_markdown")
    p.add_argument(
        "--remove-headers",
        dest="remove_headers",
        default="",
        help="Comma-separated list of frontmatter sections to omit: Cover,Tags,Description,CanonicalUrl,Series,OrgId",
    )
    p.add_argument("--api-key", dest="api_key", default=None, help="DEV.to API key (overrides DEVTO_API_KEY env var)")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="Print request and exit without sending")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    api_key: str = args.api_key or os.environ.get("DEVTO_API_KEY", "")
    if not api_key and not args.dry_run:
        print("ERROR: DEVTO_API_KEY not set. Use --api-key or export DEVTO_API_KEY.", file=sys.stderr)
        return 1

    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1

    raw = read_file(args.file)
    yaml_text, body_md = extract_front_matter(raw)
    meta = parse_simple_yaml(yaml_text)

    remove_headers = [h.strip() for h in args.remove_headers.split(",") if h.strip()]
    payload = build_payload(meta, body_md, args.publish, args.minimal, remove_headers)

    if args.article_id:
        method = "PUT"
        url = f"{DEVTO_BASE_URL}/articles/{args.article_id}"
    else:
        method = "POST"
        url = f"{DEVTO_BASE_URL}/articles"

    headers = {
        "api-key": api_key or "REDACTED",
        "Content-Type": "application/json",
        "Accept": "application/vnd.forem.api-v1+json",
    }

    if args.dry_run:
        print_dry_run(method, url, headers, payload)
        return 0

    try:
        response = do_request(method, url, headers, payload)
        print(response)
        return 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
