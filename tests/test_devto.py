"""Unit tests for devto.py — no network calls."""
import json

import pytest

from content_automation.devto import (
    build_article_payload,
    deduplicate,
    extract_front_matter,
    parse_api_response,
    parse_rss,
    parse_simple_yaml,
)


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

SAMPLE_MD = """\
---
title: "Test Article"
published: false
tags: [ai, security, devops]
description: A test description
---

# Body

Article body here.
"""


def _parse_md(raw: str) -> tuple[dict, str]:
    yaml_text, body = extract_front_matter(raw)
    meta = parse_simple_yaml(yaml_text)
    return meta, body


class TestFrontmatter:
    def test_extracts_title(self):
        meta, _ = _parse_md(SAMPLE_MD)
        assert meta["title"] == "Test Article"

    def test_extracts_tags_inline_list(self):
        meta, _ = _parse_md(SAMPLE_MD)
        assert meta["tags"] == ["ai", "security", "devops"]

    def test_parses_bool_false(self):
        meta, _ = _parse_md(SAMPLE_MD)
        assert meta["published"] is False

    def test_raises_without_front_matter(self):
        with pytest.raises(ValueError, match="YAML front matter"):
            extract_front_matter("no front matter here")

    def test_block_list_tags(self):
        raw = "---\ntitle: T\ntags:\n  - ai\n  - devops\npublished: false\n---\nbody"
        meta, _ = _parse_md(raw)
        assert meta["tags"] == ["ai", "devops"]


class TestBuildArticlePayload:
    def test_publish_flag_overrides_frontmatter(self):
        meta = {"title": "T", "published": False}
        payload = build_article_payload(meta, "body", publish_flag=True)
        assert payload["article"]["published"] is True

    def test_no_publish_flag_keeps_false(self):
        meta = {"title": "T", "published": False}
        payload = build_article_payload(meta, "body", publish_flag=False)
        assert payload["article"]["published"] is False

    def test_missing_title_raises(self):
        with pytest.raises(ValueError, match="title"):
            build_article_payload({}, "body", publish_flag=False)

    def test_minimal_omits_optional_fields(self):
        meta = {"title": "T", "published": True, "description": "desc", "tags": ["ai"]}
        payload = build_article_payload(meta, "body", publish_flag=False, minimal=True)
        article = payload["article"]
        assert "description" not in article
        assert "tags" not in article

    def test_tags_included_normally(self):
        meta = {"title": "T", "published": False, "tags": ["ai", "security"]}
        payload = build_article_payload(meta, "body", publish_flag=False, minimal=False)
        assert payload["article"]["tags"] == ["ai", "security"]

    def test_remove_headers_omits_tags(self):
        meta = {"title": "T", "published": False, "tags": ["ai"]}
        payload = build_article_payload(meta, "body", publish_flag=False, remove_headers=["Tags"])
        assert "tags" not in payload["article"]


# ---------------------------------------------------------------------------
# Curate helpers
# ---------------------------------------------------------------------------

_SAMPLE_API_JSON = json.dumps([
    {
        "title": "Article A",
        "url": "https://dev.to/user/article-a",
        "user": {"username": "alice"},
        "published_at": "2026-06-20T10:00:00Z",
        "description": "About AI",
    },
    {
        "title": "Article B",
        "url": "https://dev.to/user/article-b",
        "user": {"username": "bob"},
        "published_at": "2026-06-18T08:00:00Z",
        "description": "About security",
    },
])

_SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>RSS Article C</title>
      <link>https://dev.to/user/article-c</link>
      <pubDate>Tue, 21 Jun 2026 12:00:00 +0000</pubDate>
      <dc:creator>carol</dc:creator>
      <description><![CDATA[<p>About devops</p>]]></description>
    </item>
    <item>
      <title>RSS Article A Duplicate</title>
      <link>https://dev.to/user/article-a</link>
      <pubDate>Wed, 22 Jun 2026 09:00:00 +0000</pubDate>
      <dc:creator>alice</dc:creator>
      <description><![CDATA[<p>Duplicate of A</p>]]></description>
    </item>
  </channel>
</rss>
"""


class TestParseApiResponse:
    def test_parses_two_articles(self):
        articles = parse_api_response(_SAMPLE_API_JSON, "ai")
        assert len(articles) == 2

    def test_fields_present(self):
        articles = parse_api_response(_SAMPLE_API_JSON, "ai")
        a = articles[0]
        for field in ("title", "url", "author", "published_at", "excerpt", "_ts", "_source"):
            assert field in a

    def test_source_tag(self):
        articles = parse_api_response(_SAMPLE_API_JSON, "security")
        assert all(a["_source"] == "api:security" for a in articles)


class TestParseRss:
    def test_parses_two_items(self):
        articles = parse_rss(_SAMPLE_RSS, "devops")
        assert len(articles) == 2

    def test_extracts_title_and_url(self):
        articles = parse_rss(_SAMPLE_RSS, "devops")
        assert articles[0]["title"] == "RSS Article C"
        assert articles[0]["url"] == "https://dev.to/user/article-c"

    def test_strips_cdata_html(self):
        articles = parse_rss(_SAMPLE_RSS, "devops")
        assert "<p>" not in articles[0]["excerpt"]
        assert "CDATA" not in articles[0]["excerpt"]


class TestDeduplicate:
    def test_deduplicates_by_url(self):
        api_arts = parse_api_response(_SAMPLE_API_JSON, "ai")
        rss_arts = parse_rss(_SAMPLE_RSS, "ai")
        combined = api_arts + rss_arts
        result = deduplicate(combined, limit=10)
        urls = [a["url"] for a in result]
        # article-a appears in both api and rss — should appear once
        assert urls.count("https://dev.to/user/article-a") == 1

    def test_most_recent_first(self):
        api_arts = parse_api_response(_SAMPLE_API_JSON, "ai")
        rss_arts = parse_rss(_SAMPLE_RSS, "ai")
        combined = api_arts + rss_arts
        result = deduplicate(combined, limit=10)
        # article-a appears in both api (2026-06-20) and rss (2026-06-22).
        # Dedup keeps the NEWER timestamp (2026-06-22), so article-a sorts
        # above article-c (2026-06-21).
        urls = [a["url"] for a in result]
        idx_a = urls.index("https://dev.to/user/article-a")
        idx_c = urls.index("https://dev.to/user/article-c")
        assert idx_a < idx_c

    def test_limit_respected(self):
        api_arts = parse_api_response(_SAMPLE_API_JSON, "ai")
        rss_arts = parse_rss(_SAMPLE_RSS, "ai")
        combined = api_arts + rss_arts
        result = deduplicate(combined, limit=2)
        assert len(result) <= 2

    def test_output_strips_internal_keys(self):
        api_arts = parse_api_response(_SAMPLE_API_JSON, "ai")
        result = deduplicate(api_arts, limit=10)
        for art in result:
            assert "_ts" not in art
            assert "_source" not in art
