from pathlib import Path

import pytest

from content_automation.articles import (
    extract_front_matter,
    first_useful_paragraph,
    load_article,
    parse_simple_yaml,
)


SAMPLE = """\
---
title: "Test Article"
description: Useful summary
published: true
tags:
  - ai
  - security
---

# Test Article

This is the first useful paragraph. It explains the core idea in enough detail.
"""


def test_parse_front_matter() -> None:
    yaml_text, body = extract_front_matter(SAMPLE)
    meta = parse_simple_yaml(yaml_text)
    assert meta["title"] == "Test Article"
    assert meta["published"] is True
    assert meta["tags"] == ["ai", "security"]
    assert body.startswith("# Test Article")


def test_load_article(tmp_path: Path) -> None:
    source = tmp_path / "article.md"
    source.write_text(SAMPLE, encoding="utf-8")
    article = load_article(source)
    assert article.title == "Test Article"
    assert article.description == "Useful summary"
    assert article.tags == ["ai", "security"]


def test_missing_front_matter_raises() -> None:
    with pytest.raises(ValueError, match="front matter"):
        extract_front_matter("plain text")


def test_first_useful_paragraph_prefers_description(tmp_path: Path) -> None:
    source = tmp_path / "article.md"
    source.write_text(SAMPLE, encoding="utf-8")
    assert first_useful_paragraph(load_article(source)) == "Useful summary"
