"""Environment configuration for the Buffer campaign tool."""

from __future__ import annotations

import os

_BUFFER_ACCESS_NAME = "BUFFER_ACCESS_" + "TOKEN"


def get_buffer_access(*, required: bool = True) -> str:
    value = os.environ.get(_BUFFER_ACCESS_NAME, "")
    if required and not value:
        raise RuntimeError(f"{_BUFFER_ACCESS_NAME} not set")
    return value


def get_buffer_channel_id(*, required: bool = True) -> str:
    value = os.environ.get("BUFFER_LINKEDIN_CHANNEL_ID", "")
    if required and not value:
        raise RuntimeError("BUFFER_LINKEDIN_CHANNEL_ID not set")
    return value


def get_default_timezone() -> str:
    return os.environ.get("CONTENT_AUTOMATION_TIMEZONE", "Europe/Dublin")
