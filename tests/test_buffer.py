"""Unit tests for buffer.py — no network calls."""
import pytest

from content_automation.buffer import (
    _MUTATION_CREATE,
    _request_kwargs,
    build_input,
    format_dry_run,
)


class TestBuildInput:
    """Tests for build_input() — the CreatePostInput builder."""

    def test_link_in_body_by_default(self):
        """Link is appended to post body when first_comment=False (default)."""
        inp = build_input(
            text="Hello world",
            channel_id="ch_123",
            link="https://dev.to/article",
            scheduled_at=None,
            first_comment=False,
        )
        assert "https://dev.to/article" in inp["text"]
        assert inp["text"].startswith("Hello world")
        assert "metadata" not in inp

    def test_link_in_first_comment_when_flag_set(self):
        """With first_comment=True, link goes into metadata.linkedin.firstComment."""
        inp = build_input(
            text="Hello world",
            channel_id="ch_123",
            link="https://dev.to/article",
            scheduled_at=None,
            first_comment=True,
        )
        # Link must NOT appear in body
        assert "https://dev.to/article" not in inp["text"]
        assert inp["text"] == "Hello world"
        # Link must appear in metadata.linkedin.firstComment
        assert inp["metadata"]["linkedin"]["firstComment"] == "https://dev.to/article"

    def test_no_link_no_metadata(self):
        """When no link is supplied, metadata key should not be present."""
        inp = build_input(
            text="Hello world",
            channel_id="ch_123",
            link=None,
            scheduled_at=None,
            first_comment=False,
        )
        assert "metadata" not in inp
        assert inp["text"] == "Hello world"

    def test_required_fields_present(self):
        """All required CreatePostInput fields must be present."""
        inp = build_input(
            text="Post body",
            channel_id="ch_abc",
            link=None,
            scheduled_at=None,
            first_comment=False,
        )
        for field in ("text", "channelId", "schedulingType", "mode", "saveToDraft", "assets"):
            assert field in inp, f"Required field missing: {field}"
        assert inp["channelId"] == "ch_abc"
        assert inp["schedulingType"] == "automatic"
        assert inp["saveToDraft"] is True
        assert inp["assets"] == []

    def test_custom_schedule_sets_mode_and_due_at(self):
        """When scheduled_at is provided, mode must be customScheduled and dueAt set."""
        ts = "2026-06-30T14:00:00Z"
        inp = build_input(
            text="Scheduled post",
            channel_id="ch_123",
            link="https://example.com",
            scheduled_at=ts,
            first_comment=False,
        )
        assert inp["mode"] == "customScheduled"
        assert inp["dueAt"] == ts

    def test_no_schedule_uses_add_to_queue(self):
        """Without scheduled_at, mode must be addToQueue."""
        inp = build_input(
            text="Unscheduled",
            channel_id="ch_123",
            link=None,
            scheduled_at=None,
            first_comment=False,
        )
        assert inp["mode"] == "addToQueue"
        assert "dueAt" not in inp


class TestFormatDryRun:
    """Tests for format_dry_run() — token redaction."""

    def test_token_redacted(self):
        """The real token must not appear in dry-run output."""
        real_token = "secret-token-abc123"
        body = {"query": "...", "variables": {}}
        output = format_dry_run(real_token, body)
        assert real_token not in output
        assert "REDACTED" in output

    def test_dry_run_header_present(self):
        output = format_dry_run("tok", {"query": "q"})
        assert "DRY RUN" in output
        assert "NOT sent" in output


class TestRequestShape:
    """Tests for the Buffer GraphQL HTTP request shape."""

    def test_request_uses_json_and_bearer_auth(self):
        body = {"query": "query { account { id } }"}
        kwargs = _request_kwargs("access-value", body)

        assert kwargs["json"] == body
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["headers"]["Authorization"] == "Bearer access-value"
        assert kwargs["timeout"] == 30


class TestMutation:
    """Structural checks on the hardcoded GraphQL mutation."""

    def test_mutation_contains_required_fields(self):
        """Mutation must select __typename, post { id status dueAt }, and all error messages."""
        assert "__typename" in _MUTATION_CREATE
        assert "PostActionSuccess" in _MUTATION_CREATE
        assert "post { id status dueAt }" in _MUTATION_CREATE
        for member in (
            "NotFoundError",
            "UnauthorizedError",
            "UnexpectedError",
            "RestProxyError",
            "LimitReachedError",
            "InvalidInputError",
        ):
            assert member in _MUTATION_CREATE, f"Error member missing from mutation: {member}"
