"""Load environment variables from .env and expose typed accessors.

python-dotenv loads .env from CWD or the directory containing this file,
whichever it finds first. We force CWD-based lookup so the .env at the
project root is always picked up regardless of the import path.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the CWD first, then walk upward.  override=False means
# already-set env vars (e.g., CI injected values) take precedence.
load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)


def get_buffer_token(*, required: bool = True) -> str:
    val = os.environ.get("BUFFER_ACCESS_TOKEN", "")
    if required and not val:
        raise RuntimeError("BUFFER_ACCESS_TOKEN not set (add it to .env or export it)")
    return val


def get_buffer_channel_id(*, required: bool = True) -> str:
    val = os.environ.get("BUFFER_LINKEDIN_CHANNEL_ID", "")
    if required and not val:
        raise RuntimeError("BUFFER_LINKEDIN_CHANNEL_ID not set (add it to .env or export it)")
    return val


def get_devto_api_key(*, required: bool = True) -> str:
    val = os.environ.get("DEVTO_API_KEY", "")
    if required and not val:
        raise RuntimeError("DEVTO_API_KEY not set (add it to .env or export it)")
    return val


def get_devto_queue_file() -> str:
    return os.environ.get("DEVTO_QUEUE_FILE", "")


def get_curation_tags() -> list[str]:
    raw = os.environ.get("CURATION_TAGS", "")
    if raw.strip():
        return raw.strip().split()
    return ["ai", "security", "devops"]


def get_curation_limit() -> int:
    try:
        return int(os.environ.get("CURATION_LIMIT", "15"))
    except ValueError:
        return 15


def get_curation_output() -> str:
    from datetime import datetime
    default = f"/tmp/devto_curation_{datetime.utcnow().strftime('%Y%m%d')}.json"
    return os.environ.get("CURATION_OUTPUT", default)
