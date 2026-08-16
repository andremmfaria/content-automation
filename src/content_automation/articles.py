"""Article parsing helpers for LinkedIn campaign generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Article:
    title: str
    description: str
    tags: list[str]
    body: str
    source_path: Path


def extract_front_matter(raw: str) -> tuple[str, str]:
    match = re.match(r"^---\s*(.*?)\s*---\s*(.*)$", raw, re.DOTALL)
    if not match:
        raise ValueError("YAML front matter not found at top of file")
    return match.group(1), match.group(2).strip()


def parse_simple_yaml(yaml_text: str) -> dict[str, Any]:
    """Parse the small front matter subset used by the articles repo."""
    meta: dict[str, Any] = {}
    lines = yaml_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r"^(\w[\w_]*):\s*(.*)\s*$", line)
        if not match:
            i += 1
            continue

        key, val = match.group(1), match.group(2).strip()
        if len(val) >= 2 and val[0] in ('"', "'") and val[-1] in ('"', "'"):
            val = val[1:-1]

        if val.lower() in ("true", "false"):
            meta[key] = val.lower() == "true"
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            meta[key] = [item.strip().strip('"\'') for item in inner.split(",") if item.strip()]
        elif val == "":
            items: list[str] = []
            j = i + 1
            while j < len(lines):
                item_match = re.match(r"^\s*-\s+(.*)\s*$", lines[j])
                if not item_match:
                    break
                items.append(item_match.group(1).strip().strip('"\''))
                j += 1
            if items:
                meta[key] = items
                i = j - 1
            else:
                meta[key] = ""
        else:
            meta[key] = val
        i += 1
    return meta


def load_article(path: str | Path) -> Article:
    source = Path(path)
    raw = source.read_text(encoding="utf-8")
    yaml_text, body = extract_front_matter(raw)
    meta = parse_simple_yaml(yaml_text)

    title = str(meta.get("title") or "").strip()
    if not title:
        raise ValueError("Missing 'title' in front matter")

    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    return Article(
        title=title,
        description=str(meta.get("description") or "").strip(),
        tags=[str(tag).strip() for tag in tags if str(tag).strip()],
        body=body,
        source_path=source,
    )


def markdown_to_plain_text(markdown: str) -> str:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def first_useful_paragraph(article: Article, max_len: int = 260) -> str:
    if article.description:
        return article.description[:max_len].strip()

    for block in re.split(r"\n\s*\n", article.body):
        plain = markdown_to_plain_text(block)
        if len(plain) >= 80 and not plain.startswith("*EDIT:"):
            return plain[:max_len].strip()
    return markdown_to_plain_text(article.body)[:max_len].strip()
