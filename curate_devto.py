#!/usr/bin/env python3
"""Curate DEV.to articles for given tags.

Fetches from two sources (configurable):
  - Public Forem REST API: GET /articles?tag=<tag>&top=<days>
  - DEV.to RSS feeds:       https://dev.to/feed/tag/<tag>

Outputs a JSON array of deduplicated articles, most recent first,
limited to N (default 15).

Each item: { title, url, author, published_at, excerpt }

No authentication required.

Usage:
    python3 curate_devto.py
    python3 curate_devto.py --tags ai security kubernetes --limit 20
    python3 curate_devto.py --source api      # API only
    python3 curate_devto.py --source rss      # RSS only
    python3 curate_devto.py --dry-run         # print the requests, don't send
"""

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DEVTO_API_BASE = "https://dev.to/api"
DEVTO_RSS_BASE = "https://dev.to/feed/tag"

DEFAULT_TAGS = ["ai", "security", "devops"]
DEFAULT_LIMIT = 15
# Number of top-days to request from API (articles popular in last N days)
TOP_DAYS = 7


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> str:
    """Fetch URL and return body as string. Raises RuntimeError on failure."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "curate-devto/1.0 (content-automation)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error fetching {url}: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# API source
# ---------------------------------------------------------------------------

def api_url_for_tag(tag: str, per_page: int) -> str:
    params = urllib.parse.urlencode({
        "tag": tag,
        "top": TOP_DAYS,
        "per_page": per_page,
    })
    return f"{DEVTO_API_BASE}/articles?{params}"


def parse_api_response(raw_json: str, tag: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON parse error from API: {exc}") from exc

    articles = []
    for item in data:
        pub = item.get("published_at") or item.get("created_at") or ""
        articles.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "author": (item.get("user") or {}).get("username", ""),
            "published_at": pub,
            "excerpt": (item.get("description") or "").strip(),
            "_ts": _parse_ts(pub),
            "_source": f"api:{tag}",
        })
    return articles


def fetch_from_api(tags: List[str], limit: int, dry_run: bool) -> List[Dict[str, Any]]:
    per_tag = max(limit, 10)
    all_articles: List[Dict[str, Any]] = []
    for tag in tags:
        url = api_url_for_tag(tag, per_tag)
        if dry_run:
            print(f"[DRY RUN] GET {url}")
            continue
        try:
            raw = fetch_url(url)
            all_articles.extend(parse_api_response(raw, tag))
        except RuntimeError as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
    return all_articles


# ---------------------------------------------------------------------------
# RSS source
# ---------------------------------------------------------------------------

def rss_url_for_tag(tag: str) -> str:
    return f"{DEVTO_RSS_BASE}/{tag}"


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities for plain-text excerpts."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_ts(date_str: str) -> float:
    """Parse ISO 8601 or RFC 822 dates to a float timestamp for sorting.

    Returns 0.0 on parse failure (sorts to bottom).
    """
    if not date_str:
        return 0.0
    # ISO 8601 with Z or +00:00
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f+00:00",
    ):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    # RFC 822 (RSS pubDate): "Mon, 23 Jun 2025 12:00:00 +0000"
    try:
        import email.utils
        parsed = email.utils.parsedate_to_datetime(date_str)
        return parsed.timestamp()
    except Exception:
        pass
    return 0.0


def parse_rss(rss_text: str, tag: str) -> List[Dict[str, Any]]:
    """Minimal RSS parser using regex — no xml.etree needed for this simple feed."""
    articles = []
    # Split into <item> blocks
    items = re.findall(r"<item>(.*?)</item>", rss_text, re.DOTALL)
    for item in items:
        def tag_val(t: str) -> str:
            m = re.search(rf"<{t}[^>]*>(.*?)</{t}>", item, re.DOTALL | re.IGNORECASE)
            if not m:
                return ""
            return _strip_html(m.group(1)).strip()

        title = tag_val("title")
        link = tag_val("link")
        pub_date = tag_val("pubDate")
        # DEV.to RSS uses <dc:creator> for author
        author_m = re.search(r"<dc:creator[^>]*>(.*?)</dc:creator>", item, re.DOTALL)
        author = _strip_html(author_m.group(1)).strip() if author_m else ""
        # Excerpt from <description> — strip CDATA wrapper
        desc_m = re.search(r"<description[^>]*>(.*?)</description>", item, re.DOTALL)
        excerpt = ""
        if desc_m:
            raw_desc = desc_m.group(1)
            raw_desc = re.sub(r"<!\[CDATA\[", "", raw_desc)
            raw_desc = re.sub(r"\]\]>", "", raw_desc)
            excerpt = _strip_html(raw_desc)[:280]

        if title and link:
            articles.append({
                "title": title,
                "url": link,
                "author": author,
                "published_at": pub_date,
                "excerpt": excerpt,
                "_ts": _parse_ts(pub_date),
                "_source": f"rss:{tag}",
            })
    return articles


def fetch_from_rss(tags: List[str], dry_run: bool) -> List[Dict[str, Any]]:
    all_articles: List[Dict[str, Any]] = []
    for tag in tags:
        url = rss_url_for_tag(tag)
        if dry_run:
            print(f"[DRY RUN] GET {url}")
            continue
        try:
            raw = fetch_url(url)
            all_articles.extend(parse_rss(raw, tag))
        except RuntimeError as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
    return all_articles


# ---------------------------------------------------------------------------
# Dedup + sort + trim
# ---------------------------------------------------------------------------

def deduplicate(articles: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Deduplicate by URL (case-insensitive), keep most recent, limit to N."""
    seen: Dict[str, Dict[str, Any]] = {}
    for art in articles:
        key = art["url"].lower().rstrip("/")
        existing = seen.get(key)
        if existing is None or art["_ts"] > existing["_ts"]:
            seen[key] = art

    sorted_arts = sorted(seen.values(), key=lambda a: a["_ts"], reverse=True)

    # Strip internal keys before output
    result = []
    for art in sorted_arts[:limit]:
        result.append({
            "title": art["title"],
            "url": art["url"],
            "author": art["author"],
            "published_at": art["published_at"],
            "excerpt": art["excerpt"],
        })
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Curate DEV.to articles by tag")
    p.add_argument(
        "--tags",
        nargs="+",
        default=DEFAULT_TAGS,
        metavar="TAG",
        help=f"Tags to fetch (default: {' '.join(DEFAULT_TAGS)})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max articles to output (default: {DEFAULT_LIMIT})",
    )
    p.add_argument(
        "--source",
        choices=["api", "rss", "both"],
        default="both",
        help="Data source to use (default: both)",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print HTTP requests that would be made, without sending",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    articles: List[Dict[str, Any]] = []

    if args.source in ("api", "both"):
        articles.extend(fetch_from_api(args.tags, args.limit, args.dry_run))

    if args.source in ("rss", "both"):
        articles.extend(fetch_from_rss(args.tags, args.dry_run))

    if args.dry_run:
        print("=== DRY RUN — no requests sent ===")
        return 0

    result = deduplicate(articles, args.limit)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
