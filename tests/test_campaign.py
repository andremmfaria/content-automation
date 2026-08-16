from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from content_automation.articles import load_article
from content_automation.campaign import build_campaign, campaign_slots, hashtags, iso_z


def _article(tmp_path: Path):
    source = tmp_path / "article.md"
    source.write_text(
        """\
---
title: Hardening AI Agents
description: How a hostile prompt archive turned into a practical hardening pass.
tags: [ai, security, agents, openclaw, extra]
---

Body.
""",
        encoding="utf-8",
    )
    return load_article(source)


def test_campaign_slots_use_recommended_cadence() -> None:
    now = datetime(2026, 8, 16, 12, 0, tzinfo=ZoneInfo("Europe/Dublin"))
    launch, follow_up, lesson = campaign_slots(now=now)
    assert launch.strftime("%a %H:%M") == "Wed 16:00"
    assert follow_up.strftime("%a %H:%M") == "Fri 15:30"
    assert lesson.strftime("%a %H:%M") == "Tue 11:30"


def test_iso_z_outputs_utc() -> None:
    local = datetime(2026, 8, 19, 16, 0, tzinfo=ZoneInfo("Europe/Dublin"))
    assert iso_z(local) == "2026-08-19T15:00:00Z"


def test_hashtags_are_capped() -> None:
    assert hashtags(["ai", "security", "agents", "openclaw", "python"]).split() == [
        "#ai",
        "#security",
        "#agents",
        "#openclaw",
    ]


def test_build_campaign_returns_three_posts(tmp_path: Path) -> None:
    now = datetime(2026, 8, 16, 12, 0, tzinfo=ZoneInfo("Europe/Dublin"))
    posts = build_campaign(_article(tmp_path), "https://dev.to/example/article", now=now)
    assert [post.kind for post in posts] == ["launch", "follow_up", "lesson"]
    assert all("https://dev.to/example/article" in post.text for post in posts)
    assert all(len(post.text) <= 1300 for post in posts)


def test_build_campaign_can_omit_body_link_for_first_comment(tmp_path: Path) -> None:
    now = datetime(2026, 8, 16, 12, 0, tzinfo=ZoneInfo("Europe/Dublin"))
    posts = build_campaign(
        _article(tmp_path),
        "https://dev.to/example/article",
        now=now,
        include_link=False,
    )
    assert all("https://dev.to/example/article" not in post.text for post in posts)
