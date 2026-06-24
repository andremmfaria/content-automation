#!/usr/bin/env python3
"""Queue a LinkedIn post into Buffer as a DRAFT requiring manual approval.

Uses Buffer's GraphQL API (POST https://api.buffer.com with a createPost
mutation). Posts are created with saveToDraft=true so they sit in the Buffer
draft queue until the user approves and publishes them.

LinkedIn first-comment: Buffer's PostInputMetaData exposes a `firstComment`
field for LinkedIn. This script puts the article link there when --link is
provided. See VERIFY note below.

Required env vars:
    BUFFER_ACCESS_TOKEN       — OAuth access token
    BUFFER_LINKEDIN_CHANNEL_ID — the Buffer channel id for your LinkedIn profile

Usage:
    # Dry-run: print GraphQL request with token redacted
    python3 queue_buffer.py --text "My post body" --dry-run

    # Queue a draft (link goes in first comment)
    python3 queue_buffer.py --text "Post body" --link "https://dev.to/..."

    # Queue with a specific scheduled time (ISO 8601 UTC)
    python3 queue_buffer.py --text "Post body" --link "https://..." --at "2026-06-24T14:00:00Z"
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

BUFFER_API_URL = "https://api.buffer.com"

# ---------------------------------------------------------------------------
# GraphQL mutation builder
# ---------------------------------------------------------------------------

def build_mutation(
    text: str,
    channel_id: str,
    link: Optional[str],
    scheduled_at: Optional[str],
) -> Dict[str, Any]:
    """Build the createPost GraphQL request body.

    VERIFY: Buffer's PostInputMetaData.firstComment field for LinkedIn.
    Confirmed in reference.html#posts: `firstComment: String` is a valid
    field inside `metadata` for LinkedIn first-comment behaviour.
    If the field is rejected by your Buffer instance, move the link into
    the text body instead (see fallback comment below).

    VERIFY: schedulingType enum — the docs show `automatic` in all examples.
    For a draft the scheduling intent may not matter (saveToDraft=true parks
    it before scheduling), but `automatic` is used here as the safest default.

    VERIFY: mode enum — `addToQueue` is used when saveToDraft=true; the exact
    interaction between mode and draft state should be confirmed against your
    Buffer plan / account settings.
    """
    metadata: Dict[str, Any] = {}
    if link:
        # VERIFY: firstComment field name in PostInputMetaData for LinkedIn.
        # Source: developers.buffer.com/reference.html#posts schema extract.
        # If Buffer rejects this field, remove metadata block and append link
        # to `text` instead, e.g.: text = f"{text}\n\n{link}"
        metadata["firstComment"] = link

    # Build input object — avoid None values (GraphQL strict typing)
    post_input: Dict[str, Any] = {
        "text": text,
        "channelId": channel_id,
        "schedulingType": "automatic",
        "mode": "addToQueue",
        "saveToDraft": True,
        "assets": [],
    }

    if scheduled_at:
        # mode must be customScheduled when providing a specific dueAt time
        post_input["mode"] = "customScheduled"
        post_input["dueAt"] = scheduled_at

    if metadata:
        post_input["metadata"] = metadata

    # GraphQL over HTTP: send as { query, variables } JSON
    # Buffer accepts the mutation inline (no variables needed for simple cases)
    input_fields = _render_gql_input(post_input)
    mutation = f"""mutation CreateDraftPost {{
  createPost(input: {{{input_fields}}}) {{
    ... on PostActionSuccess {{
      post {{
        id
        text
        dueAt
        status
      }}
    }}
    ... on MutationError {{
      message
    }}
  }}
}}"""

    return {"query": mutation}


def _render_gql_input(obj: Dict[str, Any], indent: int = 4) -> str:
    """Render a Python dict as inline GraphQL input fields (not JSON).

    GraphQL input literals differ from JSON: strings use double quotes,
    booleans are lowercase, enums are unquoted identifiers.
    """
    lines = []
    pad = " " * indent
    for key, val in obj.items():
        if isinstance(val, bool):
            lines.append(f"{pad}{key}: {str(val).lower()}")
        elif isinstance(val, str) and _is_enum(key, val):
            # Enums are unquoted in GraphQL
            lines.append(f"{pad}{key}: {val}")
        elif isinstance(val, str):
            escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            lines.append(f"{pad}{key}: \"{escaped}\"")
        elif isinstance(val, list):
            lines.append(f"{pad}{key}: []")
        elif isinstance(val, dict):
            inner = _render_gql_input(val, indent + 4)
            lines.append(f"{pad}{key}: {{{inner}}}")
        elif val is None:
            lines.append(f"{pad}{key}: null")
        else:
            lines.append(f"{pad}{key}: {val}")
    return "\n" + "\n".join(lines) + "\n" + " " * (indent - 4)


# GraphQL enum fields — these must NOT be quoted
_ENUM_FIELDS = {"schedulingType", "mode"}

def _is_enum(key: str, val: str) -> bool:
    return key in _ENUM_FIELDS


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _redact_token(token: str, text: str) -> str:
    """Replace the literal token value with REDACTED in any string."""
    if token and token in text:
        return text.replace(token, "REDACTED")
    return text


def print_dry_run(token: str, body: Dict[str, Any]) -> None:
    body_str = json.dumps(body, indent=2, ensure_ascii=False)
    body_redacted = _redact_token(token, body_str)
    print("=== DRY RUN — request NOT sent ===")
    print(f"Method : POST")
    print(f"URL    : {BUFFER_API_URL}")
    print("Headers:")
    print('  Content-Type: application/json')
    print('  Authorization: Bearer REDACTED')
    print("Body (GraphQL):")
    print(body_redacted)


def do_request(token: str, body: Dict[str, Any]) -> str:
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
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body_err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body_err}") from exc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Queue a LinkedIn post in Buffer as a draft requiring approval"
    )
    p.add_argument(
        "--text",
        required=True,
        help="Post body text",
    )
    p.add_argument(
        "--link",
        default=None,
        help="Article URL — placed as LinkedIn first comment (Buffer metadata.firstComment)",
    )
    p.add_argument(
        "--at",
        dest="scheduled_at",
        default=None,
        metavar="ISO8601",
        help="Optional scheduled time in ISO 8601 UTC, e.g. 2026-06-24T14:00:00Z",
    )
    p.add_argument(
        "--access-token",
        dest="access_token",
        default=None,
        help="Buffer access token (overrides BUFFER_ACCESS_TOKEN env var)",
    )
    p.add_argument(
        "--channel-id",
        dest="channel_id",
        default=None,
        help="Buffer LinkedIn channel id (overrides BUFFER_LINKEDIN_CHANNEL_ID env var)",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print the GraphQL request with token redacted, without sending",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    token: str = args.access_token or os.environ.get("BUFFER_ACCESS_TOKEN", "")
    channel_id: str = args.channel_id or os.environ.get("BUFFER_LINKEDIN_CHANNEL_ID", "")

    if not token and not args.dry_run:
        print("ERROR: BUFFER_ACCESS_TOKEN not set.", file=sys.stderr)
        return 1
    if not channel_id and not args.dry_run:
        print("ERROR: BUFFER_LINKEDIN_CHANNEL_ID not set.", file=sys.stderr)
        return 1

    # Use placeholders in dry-run so the output is still instructive
    effective_channel = channel_id or "YOUR_CHANNEL_ID"

    body = build_mutation(
        text=args.text,
        channel_id=effective_channel,
        link=args.link,
        scheduled_at=args.scheduled_at,
    )

    if args.dry_run:
        print_dry_run(token, body)
        return 0

    try:
        response = do_request(token, body)
        print(response)
        return 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
