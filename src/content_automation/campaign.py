"""Generate a three-post LinkedIn campaign from one article."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from content_automation.articles import Article, first_useful_paragraph


DEFAULT_TIMEZONE = "Europe/Dublin"


@dataclass(frozen=True)
class CampaignPost:
    kind: str
    label: str
    text: str
    due_at_local: datetime
    due_at_utc: datetime


def _next_weekday_at(now: datetime, weekday: int, post_time: time) -> datetime:
    days = (weekday - now.weekday()) % 7
    candidate = datetime.combine(now.date() + timedelta(days=days), post_time, tzinfo=now.tzinfo)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def campaign_slots(
    *,
    now: datetime | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> tuple[datetime, datetime, datetime]:
    """Return launch/follow-up/lesson local datetimes.

    Chosen from this account's recent Buffer signal plus public LinkedIn
    benchmark data:
      - launch: Wednesday 16:00 Dublin
      - follow-up: Friday 15:30 Dublin
      - lesson: following Tuesday 11:30 Dublin
    """
    tz = ZoneInfo(timezone_name)
    current = now.astimezone(tz) if now else datetime.now(tz)
    launch = _next_weekday_at(current, 2, time(16, 0))
    follow_up = datetime.combine(launch.date() + timedelta(days=2), time(15, 30), tzinfo=tz)
    lesson = datetime.combine(launch.date() + timedelta(days=6), time(11, 30), tzinfo=tz)
    return launch, follow_up, lesson


def to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def iso_z(dt: datetime) -> str:
    return to_utc(dt).isoformat().replace("+00:00", "Z")


def hashtags(tags: list[str], limit: int = 4) -> str:
    cleaned = []
    for tag in tags:
        normalized = "".join(ch for ch in tag if ch.isalnum())
        if normalized:
            cleaned.append("#" + normalized)
    if "#LinkedIn" in cleaned:
        cleaned.remove("#LinkedIn")
    defaults = ["#AI", "#Cybersecurity", "#DevOps", "#Agents"]
    for tag in defaults:
        if len(cleaned) >= limit:
            break
        if tag not in cleaned:
            cleaned.append(tag)
    return " ".join(cleaned[:limit])


def _trim(text: str, max_chars: int = 1300) -> str:
    text = "\n".join(line.rstrip() for line in text.strip().splitlines())
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _link_block(label: str, article_url: str, include_link: bool) -> str:
    if not include_link:
        return ""
    return f"\n\n{label}\n{article_url}"


def build_launch_post(article: Article, article_url: str, *, include_link: bool = True) -> str:
    summary = first_useful_paragraph(article)
    tag_line = hashtags(article.tags)
    return _trim(
        f"""I published a new article: {article.title}

{summary}

The useful bit is not the finished setup. It is the failure mode, the tradeoff, and the part I would do differently next time.
{_link_block("Read it here:", article_url, include_link)}

{tag_line}"""
    )


def build_follow_up_post(article: Article, article_url: str, *, include_link: bool = True) -> str:
    summary = first_useful_paragraph(article)
    return _trim(
        f"""One detail from my latest article is worth pulling out on its own.

{summary}

The pattern is simple:

1. Start with the thing that failed or surprised you.
2. Explain the constraint that made the obvious answer wrong.
3. Show the boring fix.
4. Name the tradeoff honestly.

That structure works because technical readers do not need hype. They need the shape of the problem and enough evidence to decide whether it applies to them.
{_link_block("Full write-up:", article_url, include_link)}"""
    )


def build_lesson_post(article: Article, article_url: str, *, include_link: bool = True) -> str:
    tag_line = hashtags(article.tags)
    return _trim(
        f"""A rule I am keeping from writing this:

Do not turn a technical article into one LinkedIn post.

Turn it into three:

1. The launch post: what changed, why it matters, where to read it.
2. The follow-up post: the strongest idea, explained natively on LinkedIn.
3. The lesson post: the principle someone can reuse without reading the whole thing.

The article was about {article.title}.

The broader point is distribution: if the work is worth writing, it is worth packaging properly.
{_link_block("Original article:", article_url, include_link)}

{tag_line}"""
    )


def build_campaign(
    article: Article,
    article_url: str,
    *,
    now: datetime | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
    include_link: bool = True,
) -> list[CampaignPost]:
    launch_at, follow_up_at, lesson_at = campaign_slots(now=now, timezone_name=timezone_name)
    specs = [
        ("launch", "Launch post", build_launch_post(article, article_url, include_link=include_link), launch_at),
        ("follow_up", "Follow-up post", build_follow_up_post(article, article_url, include_link=include_link), follow_up_at),
        ("lesson", "Lesson post", build_lesson_post(article, article_url, include_link=include_link), lesson_at),
    ]
    return [
        CampaignPost(
            kind=kind,
            label=label,
            text=text,
            due_at_local=due_at,
            due_at_utc=to_utc(due_at),
        )
        for kind, label, text, due_at in specs
    ]
