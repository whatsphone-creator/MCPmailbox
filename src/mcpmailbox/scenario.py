"""The P0 proof: A posts text + one image URL, B lists, B acks, it is no longer pending."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

IMAGE_URL = "https://example.com/p0-diagram.png"
POST_TEXT = "P0：文字加一張圖"


@dataclass
class Agent:
    session: ClientSession

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self.session.call_tool(name, arguments)
        text = result.content[0].text if result.content else ""
        if result.is_error:
            raise AssertionError(f"{name} failed: {text}")
        return json.loads(text)


@asynccontextmanager
async def connect(url: str, token: str) -> AsyncIterator[Agent]:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield Agent(session)


async def run_p0_demo(url: str, token_a: str, token_b: str, *, agent_b: str) -> dict[str, Any]:
    """A posts to B. B lists the pending message, acks it, and neither side still sees it as pending."""
    async with connect(url, token_a) as agent_a, connect(url, token_b) as agent_b_client:
        tools = {tool.name for tool in (await agent_a.session.list_tools()).tools}
        missing = {"mailbox_post", "mailbox_list", "mailbox_ack", "mailbox_get"} - tools
        if missing:
            raise AssertionError(f"missing tools: {sorted(missing)}")

        posted = await agent_a.call(
            "mailbox_post",
            {
                "to": [agent_b],
                "text": POST_TEXT,
                "attachments": [{"type": "image", "url": IMAGE_URL}],
            },
        )
        message_id = posted["id"]
        if posted["status"] != "pending":
            raise AssertionError(posted)
        if posted["attachments"] != [{"type": "image", "url": IMAGE_URL}]:
            raise AssertionError(posted["attachments"])
        if posted["text"] != POST_TEXT or posted["cc"] != [] or posted["in_reply_to"] is not None:
            raise AssertionError(posted)

        visible = await agent_b_client.call("mailbox_list", {"status": "pending", "limit": 20})
        match = next((item for item in visible["messages"] if item["id"] == message_id), None)
        if match is None:
            raise AssertionError(f"B did not see {message_id}: {visible}")
        if match["attachments"] != [{"type": "image", "url": IMAGE_URL}]:
            raise AssertionError(match["attachments"])

        before = await agent_a.call("mailbox_get", {"id": message_id})
        if before["status"] != "pending":
            raise AssertionError(before)

        acked = await agent_b_client.call("mailbox_ack", {"id": [message_id]})
        if acked["status"] != "acked" or message_id not in acked["acked"]:
            raise AssertionError(acked)

        pending_b = await agent_b_client.call("mailbox_list", {"status": "pending"})
        if any(item["id"] == message_id for item in pending_b["messages"]):
            raise AssertionError(f"B still has pending {message_id}")

        pending_a = await agent_a.call("mailbox_list", {"status": "pending"})
        if any(item["id"] == message_id for item in pending_a["messages"]):
            raise AssertionError(f"A still lists {message_id} as pending")

        after = await agent_a.call("mailbox_get", {"id": message_id})
        if after["status"] != "acked":
            raise AssertionError(f"A still sees pending: {after}")

        kept = await agent_b_client.call("mailbox_list", {"status": "acked", "limit": 20})
        if not any(item["id"] == message_id and item["status"] == "acked" for item in kept["messages"]):
            raise AssertionError(f"acked copy missing for B: {kept}")

    return {"id": message_id, "from": posted["from"], "to": posted["to"], "status": after["status"]}
