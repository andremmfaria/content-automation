#!/usr/bin/env python3
"""Queue a LinkedIn post into Buffer as a DRAFT requiring manual approval.

Uses Buffer's GraphQL API (POST https://api.buffer.com) with a createPost
mutation. Posts are created with saveToDraft=true so they sit in the Buffer
draft queue until the user approves and publishes them.

Schema notes (verified live against the Buffer GraphQL API, 2026-06):
  - createPost(input: CreatePostInput!): PostActionPayload
  - CreatePostInput required fields: schedulingType (SchedulingType!),
    channelId (ChannelId!), mode (ShareMode!), assets (AssetInput![]!).
    Optional: text, metadata, saveToDraft, dueAt.
  - SchedulingType enum: notification | automatic
  - ShareMode enum: addToQueue | shareNow | shareNext | customScheduled
  - PostActionPayload union members: PostActionSuccess (has `post`),
    plus error members NotFoundError / UnauthorizedError / UnexpectedError /
    RestProxyError / LimitReachedError / InvalidInputError (each has `message`).

LinkedIn first comment:
  The link can be attached as a LinkedIn first comment via
  metadata.linkedin.firstComment, BUT Buffer gates that behind a PAID plan
  ("LinkedIn first comment requires a paid plan"). By default this script puts
  the link in the post body. Pass --first-comment to use the metadata path
  instead (only works on a paid Buffer plan; otherwise the API rejects it).

Required env vars:
    BUFFER_ACCESS_TOKEN        — Buffer access token (Bearer)
    BUFFER_LINKEDIN_CHANNEL_ID — the Buffer channel id for your LinkedIn profile

Usage:
    # Dry-run: print the GraphQL request (token redacted), without sending
    python3 queue_buffer.py --text "My post body" --dry-run

    # Queue a draft with the link appended to the body (free-plan friendly)
    python3 queue_buffer.py --text "Post body" --link "https://dev.to/..."

    # Use a LinkedIn first comment instead (PAID Buffer plan only)
    python3 queue_buffer.py --text "Post body" --link "https://..." --first-comment

    # Queue a draft scheduled for a specific time (ISO 8601 UTC)
    python3 queue_buffer.py --text "Post body" --link "https://..." --at "2026-06-30T14:00:00Z"
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

BUFFER_API_URL = "https://api.buffer.com"

# PostActionPayload union members that carry an error `message` field.
_ERROR_MEMBERS = (
    "NotFoundError",
    "UnauthorizedError",
    "UnexpectedError",
    "RestProxyError",
    "LimitReachedError",
    "InvalidInputError",
)

# Mutation uses GraphQL variables so the server coerces types/enums for us
# (no manual GraphQL literal rendering, no enum-quoting hacks).
_MUTATION = (
    "mutation CreateDraftPost($input: CreatePostInput!) {\n"
    "  createPost(input: $input) {\n"
    "    __typename\n"
    "    ... on PostActionSuccess { post { id status dueAt } }\n"
    + "".join(f"    ... on {m} {{ message }}\n" for m in _ERROR_MEMBERS)
    + "  }\n"
    "}"
)


def build_input(
    text: str,
    channel_id: str,
    link: Optional[str],
    scheduled_at: Optional[str],
    first_comment: bool,
) -> Dict[str, Any]:
    """Build the CreatePostInput object for the GraphQL variables."""
    body = text
    metadata: Dict[str, Any] = {}

    if link:
        if first_comment:
            # PAID plan only — Buffer rejects this on free plans.
            metadata["linkedin"] = {"firstComment": link}
        else:
            # Free-plan friendly: put the link in the post body.
            body = f"{text}\n\n{link}"

    post_input: Dict[str, Any] = {
        "text": body,
        "channelId": channel_id,
        "schedulingType": "automatic",
        "mode": "addToQueue",
        "saveToDraft": True,
        "assets": [],  # AssetInput![]! — required, empty list is valid
    }

    if scheduled_at:
        # A specific time requires the customScheduled share mode.
        post_input["mode"] = "customScheduled"
        post_input["dueAt"] = scheduled_at

    if metadata:
        post_input["metadata"] = metadata

    return post_input


def _redact(token: str, text: str) -> str:
    return text.replace(token, "REDACTED") if token and token in text else text


def print_dry_run(token: str, body: Dict[str, Any]) -> None:
    body_str = _redact(token, json.dumps(body, indent=2, ensure_ascii=False))
    print("=== DRY RUN - request NOT sent ===")
    print("Method : POST")
    print(f"URL    : {BUFFER_API_URL}")
    print("Headers:")
    print("  Content-Type: application/json")
    print("  Authorization: Bearer REDACTED")
    print("Body:")
    print(body_str)


def do_request(token: str, body: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=BUFFER_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {detail}") from exc


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Queue a LinkedIn post in Buffer as a draft requiring approval"
    )
    p.add_argument("--text", required=True, help="Post body text")
    p.add_argument(
        "--link",
        default=None,
        help="Article URL. Appended to the post body by default, or set as a "
        "LinkedIn first comment with --first-comment (paid Buffer plan only).",
    )
    p.add_argument(
        "--first-comment",
        dest="first_comment",
        action="store_true",
        help="Put --link in the LinkedIn first comment (requires a PAID Buffer plan)",
    )
    p.add_argument(
        "--at",
        dest="scheduled_at",
        default=None,
        metavar="ISO8601",
        help="Optional scheduled time in ISO 8601 UTC, e.g. 2026-06-30T14:00:00Z",
    )
    p.add_argument("--access-token", dest="access_token", default=None,
                   help="Buffer access token (overrides BUFFER_ACCESS_TOKEN)")
    p.add_argument("--channel-id", dest="channel_id", default=None,
                   help="Buffer LinkedIn channel id (overrides BUFFER_LINKEDIN_CHANNEL_ID)")
    p.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="Print the GraphQL request with token redacted, without sending")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    token = args.access_token or os.environ.get("BUFFER_ACCESS_TOKEN", "")
    channel_id = args.channel_id or os.environ.get("BUFFER_LINKEDIN_CHANNEL_ID", "")

    if not token and not args.dry_run:
        print("ERROR: BUFFER_ACCESS_TOKEN not set.", file=sys.stderr)
        return 1
    if not channel_id and not args.dry_run:
        print("ERROR: BUFFER_LINKEDIN_CHANNEL_ID not set.", file=sys.stderr)
        return 1

    post_input = build_input(
        text=args.text,
        channel_id=channel_id or "YOUR_CHANNEL_ID",
        link=args.link,
        scheduled_at=args.scheduled_at,
        first_comment=args.first_comment,
    )
    body = {"query": _MUTATION, "variables": {"input": post_input}}

    if args.dry_run:
        print_dry_run(token, body)
        return 0

    try:
        result = do_request(token, body)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = (result.get("data") or {}).get("createPost") or {}
    typename = payload.get("__typename")
    if typename == "PostActionSuccess":
        post = payload.get("post") or {}
        print(f"OK: draft created (id={post.get('id')}, status={post.get('status')})")
        return 0

    # Error union member, or a top-level GraphQL error
    message = payload.get("message") or json.dumps(result.get("errors") or result)
    print(f"ERROR: Buffer returned {typename or 'an error'}: {message}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
