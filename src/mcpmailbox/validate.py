"""Attachment and identity checks for the P0 message schema."""

from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import urlsplit

from mcpmailbox.errors import MailboxError

# Decoded-byte cap for inline data_base64 only. URL attachments are stored as
# strings and are not fetched, so this limit is not applied to them.
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENTS = 4
MAX_TEXT_CHARS = 100_000
MAX_RECIPIENTS = 20
MAX_URL_CHARS = 2048
MAX_ACK_IDS = 50
# Base64 of a 2MB payload, plus padding. Larger strings are refused before decode.
MAX_BASE64_CHARS = ((MAX_ATTACHMENT_BYTES + 2) // 3) * 4 + 8

IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
# Spec examples use ids such as grok-博士, codex-main, claude-code-workspace.
AGENT_ID_RE = re.compile(r"^[\w.\-]{1,128}$", re.UNICODE)
MESSAGE_ID_RE = re.compile(r"^msg_[0-9a-f]{32}$")


def require_agent_id(value: str, *, field: str) -> str:
    if not isinstance(value, str) or AGENT_ID_RE.fullmatch(value) is None:
        raise MailboxError(
            f"{field} must be 1-128 characters: letters, digits, underscore, dot, or hyphen"
        )
    return value


def normalize_recipients(to: list[str]) -> list[str]:
    if not isinstance(to, list) or not to:
        raise MailboxError("to must be a non-empty list of agent_id")
    if len(to) > MAX_RECIPIENTS:
        raise MailboxError(f"to accepts at most {MAX_RECIPIENTS} agent ids")
    cleaned = [require_agent_id(item, field="to") for item in to]
    if len(set(cleaned)) != len(cleaned):
        raise MailboxError("to contains a duplicate agent_id")
    return cleaned


def normalize_text(text: str, *, has_attachments: bool) -> str:
    if not isinstance(text, str):
        raise MailboxError("text must be a string")
    if len(text) > MAX_TEXT_CHARS:
        raise MailboxError(f"text exceeds {MAX_TEXT_CHARS} characters")
    if text.strip() == "" and not has_attachments:
        raise MailboxError("text is empty and there are no attachments")
    return text


def normalize_message_id(value: str, *, field: str) -> str:
    if not isinstance(value, str) or MESSAGE_ID_RE.fullmatch(value) is None:
        raise MailboxError(f"{field} must be a mailbox message id")
    return value


def _attachment_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return item
    raise MailboxError("attachment must be an object")


def _normalize_url(url: str) -> str:
    """Accept an http(s) URL string. Do not fetch it and do not size-check a remote file."""
    if not isinstance(url, str) or len(url) > MAX_URL_CHARS or any(ch.isspace() for ch in url):
        raise MailboxError("attachment url must be an http(s) URL of at most 2048 characters")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MailboxError("attachment url must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise MailboxError("attachment url must not include credentials")
    return url


def _normalize_inline(data_base64: str, mime: str | None) -> dict[str, str]:
    if not isinstance(data_base64, str) or not data_base64:
        raise MailboxError("data_base64 is empty")
    if len(data_base64) > MAX_BASE64_CHARS:
        raise MailboxError("attachment exceeds 2MB")
    if mime not in IMAGE_MIMES:
        raise MailboxError(f"mime must be one of: {', '.join(sorted(IMAGE_MIMES))}")
    try:
        raw = base64.b64decode(data_base64, validate=True)
    except Exception as exc:
        raise MailboxError("data_base64 is not valid base64") from exc
    if len(raw) == 0:
        raise MailboxError("data_base64 is empty")
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise MailboxError("attachment exceeds 2MB")
    return {"type": "image", "data_base64": data_base64, "mime": mime}


def normalize_attachments(attachments: list[Any] | None) -> list[dict[str, Any]]:
    """Return the stored attachment list.

    URL attachments are references only. The server does not fetch them, and
    the 2MB limit is not applied by downloading. That cap is the decoded size
    of inline data_base64 payloads.
    """
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise MailboxError("attachments must be a list")
    if len(attachments) > MAX_ATTACHMENTS:
        raise MailboxError(f"at most {MAX_ATTACHMENTS} attachments")
    stored: list[dict[str, Any]] = []
    for raw in attachments:
        item = _attachment_dict(raw)
        if item.get("type") != "image":
            raise MailboxError('attachment type must be "image"')
        url = item.get("url")
        data_base64 = item.get("data_base64")
        mime = item.get("mime")
        has_url = url is not None
        has_data = data_base64 is not None
        if has_url == has_data:
            raise MailboxError("attachment needs exactly one of url or data_base64")
        if has_url:
            if mime is not None:
                raise MailboxError("url attachments do not take mime")
            stored.append({"type": "image", "url": _normalize_url(url)})
        else:
            stored.append(_normalize_inline(data_base64, mime))
    return stored
