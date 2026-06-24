"""Hand-rolled Buffer GraphQL client.

Uses Buffer's GraphQL API (POST https://api.buffer.com) with Bearer auth.

There is NO maintained Buffer PyPI library for this GraphQL API — all
existing Buffer packages target the deprecated REST API and are abandoned.
This client is hand-rolled against the live GraphQL schema (verified 2026-06).

Schema notes (verified live against the Buffer GraphQL API, 2026-06):
  - createPost(input: CreatePostInput!): PostActionPayload
  - deletePost(input: DeletePostInput!): PostActionPayload
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
  ("LinkedIn first comment requires a paid plan"). By default the link goes
  in the post body. Pass first_comment=True to use the metadata path
  (only works on a paid Buffer plan; otherwise the API rejects it).
"""

import json
import urllib.error
import urllib.request
from typing import Any

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

# createPost mutation — uses GraphQL variables so the server coerces
# types/enums (no manual GraphQL literal rendering, no enum-quoting hacks).
_MUTATION_CREATE = (
    "mutation CreateDraftPost($input: CreatePostInput!) {\n"
    "  createPost(input: $input) {\n"
    "    __typename\n"
    "    ... on PostActionSuccess { post { id status dueAt } }\n"
    + "".join(f"    ... on {m} {{ message }}\n" for m in _ERROR_MEMBERS)
    + "  }\n"
    "}"
)

_MUTATION_DELETE = (
    "mutation DeletePost($input: DeletePostInput!) {\n"
    "  deletePost(input: $input) {\n"
    "    __typename\n"
    "    ... on PostActionSuccess { post { id status } }\n"
    + "".join(f"    ... on {m} {{ message }}\n" for m in _ERROR_MEMBERS)
    + "  }\n"
    "}"
)

# Queries to list channels.
# Verified live against Buffer GraphQL schema 2026-06:
#   - account.organizations gives org ids (no currentOrganization field).
#   - Top-level channels(input: {organizationId}) lists channels for an org.
#   - Channel has: id, service, name, displayName, serviceId (no `username`).
_QUERY_ACCOUNT_ORGS = """
query GetAccountOrgs {
  account {
    id
    organizations {
      id
      name
    }
  }
}
"""

_QUERY_CHANNELS = """
query ListChannels($input: ChannelsInput!) {
  channels(input: $input) {
    id
    service
    name
    displayName
    serviceId
  }
}
"""


def build_input(
    text: str,
    channel_id: str,
    link: str | None,
    scheduled_at: str | None,
    first_comment: bool,
) -> dict[str, Any]:
    """Build the CreatePostInput object for the GraphQL variables.

    By default the link is appended to the post body (free-plan friendly).
    With first_comment=True the link goes in metadata.linkedin.firstComment,
    which requires a paid Buffer plan.
    """
    body = text
    metadata: dict[str, Any] = {}

    if link:
        if first_comment:
            # PAID plan only — Buffer rejects this on free plans.
            metadata["linkedin"] = {"firstComment": link}
        else:
            # Free-plan friendly: put the link in the post body.
            body = f"{text}\n\n{link}"

    post_input: dict[str, Any] = {
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


def _redact_token(token: str, text: str) -> str:
    return text.replace(token, "REDACTED") if token and token in text else text


def _do_request(token: str, body: dict[str, Any]) -> dict[str, Any]:
    """Execute a GraphQL request against https://api.buffer.com."""
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


def format_dry_run(token: str, body: dict[str, Any]) -> str:
    """Return a dry-run summary string with the token redacted."""
    body_str = _redact_token(token, json.dumps(body, indent=2, ensure_ascii=False))
    lines = [
        "=== DRY RUN - request NOT sent ===",
        "Method : POST",
        f"URL    : {BUFFER_API_URL}",
        "Headers:",
        "  Content-Type: application/json",
        "  Authorization: Bearer REDACTED",
        "Body:",
        body_str,
    ]
    return "\n".join(lines)


def _extract_post_action_payload(
    result: dict[str, Any], operation: str
) -> dict[str, Any]:
    """Pull out the PostActionPayload from a GraphQL response."""
    payload = (result.get("data") or {}).get(operation) or {}
    return payload


def queue_draft(
    token: str,
    text: str,
    channel_id: str,
    link: str | None = None,
    scheduled_at: str | None = None,
    first_comment: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create a Buffer draft post.

    Returns a dict with keys:
      - dry_run (bool)
      - dry_run_output (str, only when dry_run=True)
      - success (bool)
      - post (dict, when success=True: {id, status, dueAt})
      - error_type (str, when success=False)
      - message (str, when success=False)
    """
    post_input = build_input(
        text=text,
        channel_id=channel_id,
        link=link,
        scheduled_at=scheduled_at,
        first_comment=first_comment,
    )
    body: dict[str, Any] = {"query": _MUTATION_CREATE, "variables": {"input": post_input}}

    if dry_run:
        return {"dry_run": True, "dry_run_output": format_dry_run(token, body)}

    result = _do_request(token, body)
    payload = _extract_post_action_payload(result, "createPost")
    typename = payload.get("__typename")

    if typename == "PostActionSuccess":
        return {"dry_run": False, "success": True, "post": payload.get("post") or {}}

    message = payload.get("message") or json.dumps(result.get("errors") or result)
    return {
        "dry_run": False,
        "success": False,
        "error_type": typename or "unknown",
        "message": message,
    }


def delete_post(
    token: str,
    post_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete a Buffer post by id.

    Returns the same shape as queue_draft.
    """
    body: dict[str, Any] = {
        "query": _MUTATION_DELETE,
        "variables": {"input": {"postId": post_id}},
    }

    if dry_run:
        return {"dry_run": True, "dry_run_output": format_dry_run(token, body)}

    result = _do_request(token, body)
    payload = _extract_post_action_payload(result, "deletePost")
    typename = payload.get("__typename")

    if typename == "PostActionSuccess":
        return {"dry_run": False, "success": True, "post": payload.get("post") or {}}

    message = payload.get("message") or json.dumps(result.get("errors") or result)
    return {
        "dry_run": False,
        "success": False,
        "error_type": typename or "unknown",
        "message": message,
    }


def list_channels(token: str) -> list[dict[str, Any]]:
    """Return all channels for every organization on the account.

    Two-step (verified live 2026-06):
      1. account.organizations → gather org ids.
      2. channels(input: {organizationId}) for each org → list channels.

    Each item: {id, service, name, displayName, serviceId}
    """
    # Step 1: get org ids
    orgs_result = _do_request(token, {"query": _QUERY_ACCOUNT_ORGS})
    errors = orgs_result.get("errors")
    if errors:
        raise RuntimeError(f"GraphQL errors fetching account orgs: {json.dumps(errors)}")

    orgs = (
        (orgs_result.get("data") or {}).get("account", {}).get("organizations") or []
    )
    if not orgs:
        return []

    # Step 2: fetch channels for each org
    all_channels: list[dict[str, Any]] = []
    for org in orgs:
        org_id = org.get("id")
        if not org_id:
            continue
        body: dict[str, Any] = {
            "query": _QUERY_CHANNELS,
            "variables": {"input": {"organizationId": org_id}},
        }
        result = _do_request(token, body)
        errors = result.get("errors")
        if errors:
            raise RuntimeError(
                f"GraphQL errors fetching channels for org {org_id}: {json.dumps(errors)}"
            )

        channels = (result.get("data") or {}).get("channels") or []
        for ch in channels:
            all_channels.append({
                "id": ch.get("id", ""),
                "service": ch.get("service", ""),
                "name": ch.get("name", ""),
                "displayName": ch.get("displayName", ""),
                "serviceId": ch.get("serviceId", ""),
            })

    return all_channels
