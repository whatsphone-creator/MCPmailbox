"""HTTP proof of the P0 mailbox flow, plus the auth and size boundaries."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mcpmailbox.scenario import run_p0_demo
from mcpmailbox.validate import MAX_ATTACHMENT_BYTES

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOKEN_A = "token-grok"
TOKEN_B = "token-codex"
TOKEN_C = "token-claude"
AGENT_A = "grok-博士"
AGENT_B = "codex-main"
AGENT_C = "claude-code-workspace"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def mailbox_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    tmp = tmp_path_factory.mktemp("mailbox")
    log_path = tmp / "server.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["MAILBOX_HOST"] = "127.0.0.1"
    env["MAILBOX_PORT"] = str(port)
    env["MAILBOX_DB"] = str(tmp / "mailbox.sqlite")
    env["MAILBOX_PUBLIC_URL"] = url
    env["MAILBOX_TOKENS"] = json.dumps(
        {TOKEN_A: AGENT_A, TOKEN_B: AGENT_B, TOKEN_C: AGENT_C},
        ensure_ascii=False,
    )
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcpmailbox"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 20
    healthy = False
    while time.time() < deadline:
        if proc.poll() is not None:
            log.flush()
            raise RuntimeError(log_path.read_text(encoding="utf-8"))
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                healthy = response.status == 200
                if healthy:
                    break
        except Exception:
            time.sleep(0.1)
    if not healthy:
        proc.terminate()
        log.flush()
        raise RuntimeError(log_path.read_text(encoding="utf-8") or "server did not start")
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def test_p0_post_list_ack(mailbox_url: str) -> None:
    summary = asyncio.run(run_p0_demo(mailbox_url, TOKEN_A, TOKEN_B, agent_b=AGENT_B))
    assert summary["from"] == AGENT_A
    assert summary["to"] == [AGENT_B]
    assert summary["status"] == "acked"
    assert summary["id"].startswith("msg_")


def test_missing_and_unknown_bearer_are_rejected(mailbox_url: str) -> None:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
    ).encode()
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    missing_request = urllib.request.Request(mailbox_url, data=body, method="POST", headers=headers)
    with pytest.raises(urllib.error.HTTPError) as missing:
        urllib.request.urlopen(missing_request, timeout=5)
    assert missing.value.code == 401

    unknown_request = urllib.request.Request(
        mailbox_url,
        data=body,
        method="POST",
        headers={**headers, "Authorization": "Bearer not-a-real-token"},
    )
    with pytest.raises(urllib.error.HTTPError) as unknown:
        urllib.request.urlopen(unknown_request, timeout=5)
    assert unknown.value.code == 401


async def _call(url: str, token: str, name: str, arguments: dict) -> tuple[bool, dict | str]:
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                text = result.content[0].text if result.content else ""
                if result.is_error:
                    return True, text
                return False, json.loads(text)


def test_sender_cannot_ack_and_stranger_cannot_read(mailbox_url: str) -> None:
    posted_error, posted = asyncio.run(
        _call(
            mailbox_url,
            TOKEN_A,
            "mailbox_post",
            {
                "to": [AGENT_B],
                "text": "only B",
                "attachments": [{"type": "image", "url": "https://example.com/only-b.png"}],
            },
        )
    )
    assert posted_error is False
    assert isinstance(posted, dict)
    message_id = posted["id"]

    ack_error, ack_text = asyncio.run(_call(mailbox_url, TOKEN_A, "mailbox_ack", {"id": [message_id]}))
    assert ack_error is True
    assert "not addressed" in str(ack_text)

    stranger_error, stranger_text = asyncio.run(_call(mailbox_url, TOKEN_C, "mailbox_get", {"id": message_id}))
    assert stranger_error is True
    assert "not found" in str(stranger_text)

    listed_error, listed = asyncio.run(_call(mailbox_url, TOKEN_C, "mailbox_list", {}))
    assert listed_error is False
    assert isinstance(listed, dict)
    assert all(item["id"] != message_id for item in listed["messages"])


def test_inline_image_over_two_megabytes_is_rejected(mailbox_url: str) -> None:
    payload = base64.b64encode(b"y" * (MAX_ATTACHMENT_BYTES + 1)).decode()
    failed, text = asyncio.run(
        _call(
            mailbox_url,
            TOKEN_A,
            "mailbox_post",
            {
                "to": [AGENT_B],
                "text": "too big",
                "attachments": [{"type": "image", "data_base64": payload, "mime": "image/png"}],
            },
        )
    )
    assert failed is True
    assert "2MB" in str(text)
