"""Click CLI entry point for content-automation.

Console script: content-automation
Usage: content-automation [GROUP] [COMMAND] [OPTIONS]

Groups:
  devto   — publish and curate DEV.to articles
  buffer  — queue and manage Buffer drafts

Top-level commands:
  run-weekly — orchestration replacing run_weekly.sh
"""
import json
import sys

import click

from content_automation import buffer as buf
from content_automation import config
from content_automation import devto


# ---------------------------------------------------------------------------
# Top-level group
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Content automation: DEV.to publishing and LinkedIn draft queuing via Buffer."""


# ---------------------------------------------------------------------------
# devto group
# ---------------------------------------------------------------------------

@cli.group()
def devto_cmd() -> None:
    """DEV.to article publishing and curation."""


# Rename the group to match the desired CLI name "devto"
devto_cmd.name = "devto"
cli.add_command(devto_cmd, name="devto")


@devto_cmd.command("publish")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True), help="Markdown file with YAML frontmatter")
@click.option("--id", "article_id", default=None, help="Existing article id for update (PUT)")
@click.option("--publish", "publish_flag", is_flag=True, help="Force published=true regardless of frontmatter")
@click.option("--minimal", is_flag=True, help="Send only title / published / body_markdown")
@click.option("--remove-headers", default="", help="Comma-separated frontmatter sections to omit: Cover,Tags,Description,CanonicalUrl,Series,OrgId")
@click.option("--dry-run", is_flag=True, help="Print request with token REDACTED; do not send")
def devto_publish(
    file_path: str,
    article_id: str | None,
    publish_flag: bool,
    minimal: bool,
    remove_headers: str,
    dry_run: bool,
) -> None:
    """Publish or update a DEV.to article from a Markdown file."""
    try:
        api_key = config.get_devto_api_key(required=not dry_run)
    except RuntimeError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    remove_list = [h.strip() for h in remove_headers.split(",") if h.strip()]

    result = devto.publish_article(
        api_key=api_key,
        file_path=file_path,
        article_id=article_id,
        publish_flag=publish_flag,
        minimal=minimal,
        remove_headers=remove_list,
        dry_run=dry_run,
    )

    if result.get("dry_run"):
        click.echo(result["dry_run_output"])
        return

    if result.get("success"):
        click.echo(result["response"])
    else:
        click.echo(f"ERROR: {result['message']}", err=True)
        sys.exit(2)


@devto_cmd.command("curate")
@click.option("--tags", multiple=True, default=["ai", "security", "devops"], show_default=True, help="DEV.to tags to fetch")
@click.option("--source", type=click.Choice(["api", "rss", "both"]), default="both", show_default=True, help="Data source")
@click.option("--limit", type=int, default=15, show_default=True, help="Max articles to output")
@click.option("--output", default="-", help="Output path (default: stdout, use - for stdout)")
@click.option("--dry-run", is_flag=True, help="Print HTTP requests that would be made; do not send")
def devto_curate(
    tags: tuple[str, ...],
    source: str,
    limit: int,
    output: str,
    dry_run: bool,
) -> None:
    """Fetch and curate recent DEV.to articles by tag."""
    tag_list = list(tags) if tags else devto.DEFAULT_TAGS

    if dry_run:
        devto.curate(tags=tag_list, limit=limit, source=source, dry_run=True)
        click.echo("=== DRY RUN — no requests sent ===")
        return

    articles = devto.curate(tags=tag_list, limit=limit, source=source)
    result_json = json.dumps(articles, indent=2, ensure_ascii=False)

    if output == "-":
        click.echo(result_json)
    else:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(result_json + "\n")
        click.echo(f"Curation results written to {output}")


# ---------------------------------------------------------------------------
# buffer group
# ---------------------------------------------------------------------------

@cli.group()
def buffer_cmd() -> None:
    """Buffer draft management for LinkedIn."""


buffer_cmd.name = "buffer"
cli.add_command(buffer_cmd, name="buffer")


@buffer_cmd.command("queue")
@click.option("--text", required=True, help="Post body text")
@click.option("--link", default=None, help="Article URL — appended to body by default; use --first-comment for paid LinkedIn first-comment")
@click.option("--first-comment", "first_comment", is_flag=True, help="Put --link in LinkedIn first comment (PAID Buffer plan only)")
@click.option("--at", "scheduled_at", default=None, metavar="ISO8601", help="Scheduled time in ISO 8601 UTC, e.g. 2026-06-30T14:00:00Z")
@click.option("--dry-run", is_flag=True, help="Print GraphQL request with token REDACTED; do not send")
def buffer_queue(
    text: str,
    link: str | None,
    first_comment: bool,
    scheduled_at: str | None,
    dry_run: bool,
) -> None:
    """Queue a LinkedIn post in Buffer as a draft requiring manual approval."""
    try:
        token = config.get_buffer_token(required=not dry_run)
        channel_id = config.get_buffer_channel_id(required=not dry_run)
    except RuntimeError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    result = buf.queue_draft(
        token=token or "DUMMY",
        text=text,
        channel_id=channel_id or "YOUR_CHANNEL_ID",
        link=link,
        scheduled_at=scheduled_at,
        first_comment=first_comment,
        dry_run=dry_run,
    )

    if result.get("dry_run"):
        click.echo(result["dry_run_output"])
        return

    if result.get("success"):
        post = result["post"]
        click.echo(f"OK: draft created (id={post.get('id')}, status={post.get('status')})")
    else:
        click.echo(f"ERROR: Buffer returned {result.get('error_type', 'an error')}: {result.get('message')}", err=True)
        sys.exit(3)


@buffer_cmd.command("channels")
def buffer_channels() -> None:
    """List all Buffer channels (id, service, name) for the account.

    Use this to find your LinkedIn channel id for BUFFER_LINKEDIN_CHANNEL_ID.
    """
    try:
        token = config.get_buffer_token()
    except RuntimeError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    try:
        channels = buf.list_channels(token)
    except RuntimeError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    if not channels:
        click.echo("No channels found.")
        return

    click.echo(f"{'ID':<30}  {'SERVICE':<15}  {'NAME':<30}  DISPLAY_NAME / SERVICE_ID")
    click.echo("-" * 100)
    for ch in channels:
        extra = ch.get("displayName") or ch.get("serviceId") or ""
        click.echo(f"{ch['id']:<30}  {ch['service']:<15}  {ch['name']:<30}  {extra}")


@buffer_cmd.command("delete")
@click.option("--id", "post_id", required=True, help="Buffer post id to delete")
@click.option("--dry-run", is_flag=True, help="Print GraphQL request with token REDACTED; do not send")
def buffer_delete(post_id: str, dry_run: bool) -> None:
    """Delete a Buffer draft post by id."""
    try:
        token = config.get_buffer_token(required=not dry_run)
    except RuntimeError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    result = buf.delete_post(
        token=token or "DUMMY",
        post_id=post_id,
        dry_run=dry_run,
    )

    if result.get("dry_run"):
        click.echo(result["dry_run_output"])
        return

    if result.get("success"):
        post = result["post"]
        click.echo(f"OK: post deleted (id={post.get('id')}, status={post.get('status')})")
    else:
        click.echo(f"ERROR: Buffer returned {result.get('error_type', 'an error')}: {result.get('message')}", err=True)
        sys.exit(3)


# ---------------------------------------------------------------------------
# run-weekly command
# ---------------------------------------------------------------------------

@cli.command("run-weekly")
@click.option("--dry-run", is_flag=True, help="Print all requests with token REDACTED; do not send")
def run_weekly(dry_run: bool) -> None:
    """Weekly orchestration: publish next DEV.to article + curate candidates.

    Replaces run_weekly.sh. Schedule: Tuesday 14:00 UTC (0 14 * * 2) = 10:00 ET / 16:00 CEST.

    What this command does:
      1. Publishes the next queued DEV.to article (if DEVTO_QUEUE_FILE is set)
      2. Gathers curation candidates and writes them to CURATION_OUTPUT
      3. Exits — LinkedIn drafting is NOT done here.

    LinkedIn drafting step:
      After this command exits, the OpenClaw agent reads CURATION_OUTPUT,
      selects or drafts a LinkedIn post, and calls:
        content-automation buffer queue --text <post> --link <url>
      This separation keeps orchestration free of LLM logic and lets the
      agent iterate on the post text without re-running the pipeline.
    """
    if dry_run:
        click.echo("[run-weekly] DRY_RUN — no real HTTP requests will be sent.")

    # ------------------------------------------------------------------
    # Step 1: Publish next queued DEV.to article
    # ------------------------------------------------------------------
    click.echo("[run-weekly] Step 1: Publish DEV.to article")

    queue_file = config.get_devto_queue_file()
    if not queue_file:
        click.echo("[run-weekly]   DEVTO_QUEUE_FILE not set — skipping publish step.")
    else:
        import os
        if not os.path.isfile(queue_file):
            click.echo(f"[run-weekly]   Queue file not found: {queue_file} — skipping.", err=True)
        else:
            with open(queue_file, encoding="utf-8") as fh:
                next_article = fh.readline().strip()

            if not next_article:
                click.echo("[run-weekly]   Queue file is empty — nothing to publish.")
            else:
                click.echo(f"[run-weekly]   Publishing: {next_article}")
                try:
                    api_key = config.get_devto_api_key(required=not dry_run)
                except RuntimeError as exc:
                    click.echo(f"ERROR: {exc}", err=True)
                    sys.exit(1)

                result = devto.publish_article(
                    api_key=api_key or "REDACTED",
                    file_path=next_article,
                    publish_flag=True,
                    dry_run=dry_run,
                )
                if result.get("dry_run"):
                    click.echo(result["dry_run_output"])
                elif result.get("success"):
                    click.echo("[run-weekly]   Publish complete.")
                else:
                    click.echo(f"[run-weekly]   Publish ERROR: {result['message']}", err=True)

    # ------------------------------------------------------------------
    # Step 2: Curate DEV.to articles
    # ------------------------------------------------------------------
    click.echo("[run-weekly] Step 2: Curate DEV.to articles")

    tags = config.get_curation_tags()
    limit = config.get_curation_limit()
    output_path = config.get_curation_output()

    if dry_run:
        devto.curate(tags=tags, limit=limit, dry_run=True)
        click.echo(f"[run-weekly]   Dry-run: curation output would be written to {output_path}")
    else:
        articles = devto.curate(tags=tags, limit=limit)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(articles, indent=2, ensure_ascii=False) + "\n")
        click.echo(f"[run-weekly]   Curation results written to {output_path}")

    # ------------------------------------------------------------------
    # Step 3: LinkedIn drafting (handled by the agent, not this command)
    # ------------------------------------------------------------------
    click.echo("[run-weekly] Step 3: LinkedIn drafting")
    click.echo("[run-weekly]   This step is handled by the OpenClaw agent.")
    click.echo(f"[run-weekly]   The agent reads {output_path}, drafts a LinkedIn post,")
    click.echo("[run-weekly]   and calls: content-automation buffer queue --text <post> --link <url>")
    click.echo("[run-weekly]   The post lands in Buffer as a draft requiring manual approval.")

    click.echo("[run-weekly] Done. Check Buffer drafts for the LinkedIn post to approve.")
