"""CLI for article-to-LinkedIn campaign automation."""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from content_automation import buffer as buffer_api
from content_automation import config
from content_automation.articles import load_article
from content_automation.campaign import DEFAULT_TIMEZONE, build_campaign, iso_z


@click.group()
def cli() -> None:
    """Generate and draft LinkedIn campaigns for DEV.to articles."""


@cli.group()
def buffer() -> None:
    """Read Buffer account/channel information."""


@buffer.command("channels")
def buffer_channels() -> None:
    """List all Buffer channels available to the configured account."""
    try:
        auth = config.get_buffer_access(required=True)
        channels = buffer_api.BufferClient(auth).list_channels()
    except RuntimeError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    if not channels:
        click.echo("No channels found.")
        return

    click.echo(f"{'ID':<30}  {'SERVICE':<15}  {'NAME':<30}  DISPLAY_NAME / SERVICE_ID")
    click.echo("-" * 100)
    for channel in channels:
        extra = channel.get("displayName") or channel.get("serviceId") or ""
        click.echo(f"{channel['id']:<30}  {channel['service']:<15}  {channel['name']:<30}  {extra}")


@cli.group()
def campaign() -> None:
    """Build LinkedIn campaign drafts from article markdown."""


@campaign.command("article")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True), help="Article markdown file")
@click.option("--url", "article_url", required=True, help="Published DEV.to article URL")
@click.option("--channel-id", default=None, help="Buffer channel id; defaults to BUFFER_LINKEDIN_CHANNEL_ID")
@click.option("--timezone", "timezone_name", default=DEFAULT_TIMEZONE, show_default=True, help="Scheduling timezone")
@click.option("--first-comment", is_flag=True, help="Put the URL in LinkedIn first comment; paid Buffer plan only")
@click.option("--create-drafts", is_flag=True, help="Create scheduled Buffer drafts. Without this, only print the plan.")
@click.option("--json-output", is_flag=True, help="Print machine-readable JSON")
def campaign_article(
    file_path: str,
    article_url: str,
    channel_id: str | None,
    timezone_name: str,
    first_comment: bool,
    create_drafts: bool,
    json_output: bool,
) -> None:
    """Create a launch/follow-up/lesson campaign for one article.

    The command is dry-run by default. Passing --create-drafts creates Buffer
    drafts only; Buffer still requires manual approval before publication.
    """
    try:
        article = load_article(file_path)
        posts = build_campaign(
            article,
            article_url,
            timezone_name=timezone_name,
            include_link=not first_comment,
        )
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    results: list[dict[str, Any]] = []
    auth = ""
    target_channel = channel_id or ""

    if create_drafts:
        try:
            auth = config.get_buffer_access(required=True)
            target_channel = channel_id or config.get_buffer_channel_id(required=True)
            client = buffer_api.BufferClient(auth)
        except RuntimeError as exc:
            click.echo(f"ERROR: {exc}", err=True)
            sys.exit(1)
    else:
        target_channel = channel_id or config.get_buffer_channel_id(required=False) or "BUFFER_LINKEDIN_CHANNEL_ID"

    for post in posts:
        due_at = iso_z(post.due_at_local)
        if create_drafts:
            result = client.queue_draft(
                post.text,
                target_channel,
                article_url if first_comment else None,
                due_at,
                first_comment,
                False,
            )
            if not result.get("success"):
                click.echo(
                    f"ERROR: Buffer returned {result.get('error_type', 'an error')}: {result.get('message')}",
                    err=True,
                )
                sys.exit(3)
            created = result.get("post") or {}
            results.append(
                {
                    "kind": post.kind,
                    "label": post.label,
                    "status": created.get("status"),
                    "post_id": created.get("id"),
                    "due_at": created.get("dueAt") or due_at,
                    "channel_id": target_channel,
                }
            )
        else:
            results.append(
                {
                    "kind": post.kind,
                    "label": post.label,
                    "due_at_local": post.due_at_local.isoformat(),
                    "due_at_utc": due_at,
                    "channel_id": target_channel,
                    "text": post.text,
                }
            )

    if json_output:
        click.echo(json.dumps({"article": article.title, "posts": results}, indent=2, ensure_ascii=False))
        return

    if create_drafts:
        click.echo(f"Created {len(results)} Buffer drafts for: {article.title}")
        for item in results:
            click.echo(f"- {item['label']}: id={item['post_id']} status={item['status']} due={item['due_at']}")
        click.echo("Review and approve the drafts in Buffer before they publish.")
        return

    click.echo(f"Campaign plan for: {article.title}")
    click.echo("")
    for item in results:
        click.echo(f"## {item['label']} ({item['due_at_local']})")
        click.echo(item["text"])
        click.echo("")


if __name__ == "__main__":
    cli()
