"""DEV.to / Forem API client: publish articles and curate tag feeds.

Combines logic from publish_devto.py and curate_devto.py.
All HTTP is on stdlib urllib — no third-party HTTP deps.

Publish/update:
  - POST /articles  (create)
  - PUT  /articles/{id}  (update)
  Reads DEVTO_API_KEY via config.

Curate:
  - Public Forem REST API: GET /articles?tag=<tag>&top=<days>
  - DEV.to RSS feeds:       https://dev.to/feed/tag/<tag>
  No authentication required.
"""

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

DEVTO_BASE_URL = "https://dev.to/api"
DEVTO_RSS_BASE = "https://dev.to/feed/tag"

# Number of top-days to request from API (articles popular in last N days)
TOP_DAYS = 7
DEFAULT_TAGS = ["ai", "security", "devops"]
DEFAULT_LIMIT = 15


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def extract_front_matter(raw: str) -> tuple[str, str]:
    m = re.match(r"^---\s*(.*?)\s*---\s*(.*)$", raw, re.DOTALL)
    if not m:
        raise ValueError("YAML front matter not found at top of file")
    return m.group(1), m.group(2)


def parse_simple_yaml(yaml_text: str) -> dict[str, Any]:
    """Minimal YAML parser for single-level DEV.to frontmatter.

    Handles: scalars, booleans, inline lists ([a, b]), and block lists (- item).
    No external deps.
    """
    meta: dict[str, Any] = {}
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
                items: list[str] = []
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


def build_article_payload(
    meta: dict[str, Any],
    body_markdown: str,
    publish_flag: bool,
    minimal: bool = False,
    remove_headers: list[str] | None = None,
) -> dict[str, Any]:
    """Build the Forem API article payload dict."""
    remove_headers = remove_headers or []
    title = meta.get("title")
    if not title:
        raise ValueError("Missing 'title' in frontmatter")

    published = meta.get("published", False)
    if publish_flag:
        published = True

    article: dict[str, Any] = {
        "title": title,
        "published": bool(published),
        "body_markdown": body_markdown,
    }

    if not minimal:
        if meta.get("description") and "Description" not in remove_headers:
            article["description"] = meta["description"]
        tags = meta.get("tags") or []
        if isinstance(tags, list) and tags and "Tags" not in remove_headers:
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

def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers with secret values replaced by REDACTED."""
    redacted = {}
    for k, v in headers.items():
        redacted[k] = "REDACTED" if k.lower() in ("api-key", "authorization") else v
    return redacted


def format_dry_run(method: str, url: str, headers: dict[str, str], payload: dict[str, Any]) -> str:
    lines = [
        "=== DRY RUN — request NOT sent ===",
        f"Method : {method}",
        f"URL    : {url}",
        f"Headers: {json.dumps(_redact_headers(headers), indent=2)}",
        "Body   :",
        json.dumps(payload, indent=2, ensure_ascii=False),
    ]
    return "\n".join(lines)


def _fetch_url(url: str) -> str:
    """Fetch URL and return body as string."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "content-automation/1.0 (curate-devto)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error fetching {url}: {exc.reason}") from exc


def _do_request(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
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
# Publish / update
# ---------------------------------------------------------------------------

def publish_article(
    api_key: str,
    file_path: str,
    article_id: str | None = None,
    publish_flag: bool = False,
    minimal: bool = False,
    remove_headers: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish or update a DEV.to article from a Markdown file.

    Returns:
      - dry_run (bool)
      - dry_run_output (str, when dry_run=True)
      - success (bool, when dry_run=False)
      - response (str, when success=True)
      - message (str, when success=False)
    """
    raw = read_file(file_path)
    yaml_text, body_md = extract_front_matter(raw)
    meta = parse_simple_yaml(yaml_text)
    payload = build_article_payload(meta, body_md, publish_flag, minimal, remove_headers or [])

    if article_id:
        method = "PUT"
        url = f"{DEVTO_BASE_URL}/articles/{article_id}"
    else:
        method = "POST"
        url = f"{DEVTO_BASE_URL}/articles"

    headers = {
        "api-key": api_key or "REDACTED",
        "Content-Type": "application/json",
        "Accept": "application/vnd.forem.api-v1+json",
    }

    if dry_run:
        return {"dry_run": True, "dry_run_output": format_dry_run(method, url, headers, payload)}

    try:
        response = _do_request(method, url, headers, payload)
        return {"dry_run": False, "success": True, "response": response}
    except RuntimeError as exc:
        return {"dry_run": False, "success": False, "message": str(exc)}


# ---------------------------------------------------------------------------
# Curate
# ---------------------------------------------------------------------------

def _parse_ts(date_str: str) -> float:
    """Parse ISO 8601 or RFC 822 dates to a float timestamp for sorting.

    Returns 0.0 on parse failure (sorts to bottom).
    """
    if not date_str:
        return 0.0
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


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities for plain-text excerpts."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _api_url_for_tag(tag: str, per_page: int) -> str:
    params = urllib.parse.urlencode({"tag": tag, "top": TOP_DAYS, "per_page": per_page})
    return f"{DEVTO_BASE_URL}/articles?{params}"


def parse_api_response(raw_json: str, tag: str) -> list[dict[str, Any]]:
    """Parse Forem API JSON response into normalized article dicts."""
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


def parse_rss(rss_text: str, tag: str) -> list[dict[str, Any]]:
    """Parse a DEV.to RSS feed into normalized article dicts.

    Uses regex — no xml.etree needed for this simple feed structure.
    """
    articles = []
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
        author_m = re.search(r"<dc:creator[^>]*>(.*?)</dc:creator>", item, re.DOTALL)
        author = _strip_html(author_m.group(1)).strip() if author_m else ""
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


def deduplicate(articles: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Deduplicate by URL (case-insensitive), keep most recent, limit to N."""
    seen: dict[str, dict[str, Any]] = {}
    for art in articles:
        key = art["url"].lower().rstrip("/")
        existing = seen.get(key)
        if existing is None or art["_ts"] > existing["_ts"]:
            seen[key] = art

    sorted_arts = sorted(seen.values(), key=lambda a: a["_ts"], reverse=True)

    return [
        {
            "title": art["title"],
            "url": art["url"],
            "author": art["author"],
            "published_at": art["published_at"],
            "excerpt": art["excerpt"],
        }
        for art in sorted_arts[:limit]
    ]


def curate(
    tags: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    source: str = "both",
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Fetch and deduplicate DEV.to articles for the given tags.

    source: "api" | "rss" | "both"
    Returns normalized list or empty list on dry_run.
    """
    tags = tags or DEFAULT_TAGS
    articles: list[dict[str, Any]] = []

    if source in ("api", "both"):
        per_tag = max(limit, 10)
        for tag in tags:
            url = _api_url_for_tag(tag, per_tag)
            if dry_run:
                print(f"[DRY RUN] GET {url}")
                continue
            try:
                raw = _fetch_url(url)
                articles.extend(parse_api_response(raw, tag))
            except RuntimeError as exc:
                import sys
                print(f"WARNING: {exc}", file=sys.stderr)

    if source in ("rss", "both"):
        for tag in tags:
            url = f"{DEVTO_RSS_BASE}/{tag}"
            if dry_run:
                print(f"[DRY RUN] GET {url}")
                continue
            try:
                raw = _fetch_url(url)
                articles.extend(parse_rss(raw, tag))
            except RuntimeError as exc:
                import sys
                print(f"WARNING: {exc}", file=sys.stderr)

    if dry_run:
        return []

    return deduplicate(articles, limit)
