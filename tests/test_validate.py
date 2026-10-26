import base64

import pytest

from mcpmailbox.errors import MailboxError
from mcpmailbox.validate import MAX_ATTACHMENT_BYTES, normalize_attachments, normalize_recipients


def test_image_url_attachment() -> None:
    stored = normalize_attachments([{"type": "image", "url": "https://example.com/a.png"}])
    assert stored == [{"type": "image", "url": "https://example.com/a.png"}]


def test_rejects_oversize_inline_image() -> None:
    payload = base64.b64encode(b"x" * (MAX_ATTACHMENT_BYTES + 1)).decode()
    with pytest.raises(MailboxError, match="2MB"):
        normalize_attachments([{"type": "image", "data_base64": payload, "mime": "image/png"}])


def test_accepts_exactly_two_megabytes() -> None:
    payload = base64.b64encode(b"x" * MAX_ATTACHMENT_BYTES).decode()
    stored = normalize_attachments([{"type": "image", "data_base64": payload, "mime": "image/png"}])
    assert stored[0]["mime"] == "image/png"


def test_rejects_fifth_attachment_and_file_url() -> None:
    items = [{"type": "image", "url": f"https://example.com/{index}.png"} for index in range(5)]
    with pytest.raises(MailboxError, match="4"):
        normalize_attachments(items)
    with pytest.raises(MailboxError, match="http"):
        normalize_attachments([{"type": "image", "url": "file:///tmp/secret.png"}])


def test_rejects_duplicate_recipients() -> None:
    with pytest.raises(MailboxError, match="duplicate"):
        normalize_recipients(["codex-main", "codex-main"])
