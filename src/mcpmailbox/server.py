"""Streamable HTTP MCP server for mailbox_post, mailbox_list, mailbox_ack, mailbox_get."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcpmailbox.auth import MAILBOX_SCOPE, StaticTokenVerifier
from mcpmailbox.config import Settings
from mcpmailbox.errors import MailboxError
from mcpmailbox.store import MailboxStore

# Four inline 2MB images, base64-encoded, plus JSON. The per-file cap is still 2MB.
MAX_HTTP_BODY = 16 * 1024 * 1024

INSTRUCTIONS = """
你是這把 Bearer token 所綁定的 agent。MCPmailbox 沒有推播。
醒來時呼叫 mailbox_list（status=pending），處理後 mailbox_ack。
要回覆就 mailbox_post。只看得到 to/cc 含自己的信；寄件者用 mailbox_get 看狀態。
沒有群組房間、沒有 Telegram/Slack、沒有語音。圖片最多 4 個，每個最多 2MB。
""".strip()


class Attachment(BaseModel):
    """One image, either a URL reference or inline base64. Not both."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["image"]
    url: str | None = None
    data_base64: str | None = None
    mime: str | None = None


def _agent_id() -> str:
    token = get_access_token()
    if token is None or not token.client_id:
        raise ToolError("missing bearer token")
    return token.client_id


def _call(action: Any) -> Any:
    try:
        return action()
    except MailboxError as exc:
        raise ToolError(str(exc)) from exc


def build_server(settings: Settings) -> MCPServer:
    store = MailboxStore(settings.db_path)
    store.migrate()
    mcp = MCPServer(
        "MCPmailbox",
        instructions=INSTRUCTIONS,
        token_verifier=StaticTokenVerifier(settings.tokens),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("https://mcpmailbox.local"),
            resource_server_url=AnyHttpUrl(settings.public_url),
            required_scopes=[MAILBOX_SCOPE],
            validate_token_resource=False,
        ),
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.tool(structured_output=False)
    def mailbox_post(
        to: Annotated[list[str], Field(description="收件 agent_id。至少一個。這不是群組房間。")],
        text: Annotated[str, Field(description="訊息本文。沒有附件時不可空白。")],
        attachments: Annotated[
            list[Attachment] | None,
            Field(description='圖片附件，最多 4 個。每項 {type:"image",url} 或 {type:"image",data_base64,mime}。'),
        ] = None,
        in_reply_to: Annotated[str | None, Field(description="被回覆的 msg_ id。可省略。")] = None,
    ) -> dict[str, Any]:
        """寄一則信。from 是這把 token 的 agent_id。cc 在 P0 固定為空陣列。"""
        sender = _agent_id()
        return _call(
            lambda: store.post(
                sender=sender,
                to=to,
                text=text,
                attachments=attachments,
                in_reply_to=in_reply_to,
            )
        )

    @mcp.tool(structured_output=False)
    def mailbox_list(
        status: Annotated[
            Literal["pending", "acked"],
            Field(description="pending 只回尚未 ack 的信。acked 只回已 ack 的信。"),
        ] = "pending",
        limit: Annotated[int, Field(description="最多幾則。預設 20，上限 100。", ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        """列出 to 或 cc 含自己的信。看不到別人的信，也看不到自己寄出、自己不在 to/cc 的信。"""
        agent_id = _agent_id()
        messages = _call(lambda: store.list_messages(agent_id=agent_id, status=status, limit=limit))
        return {"messages": messages}

    @mcp.tool(structured_output=False)
    def mailbox_ack(
        id: Annotated[list[str], Field(description="要標成 acked 的 msg_ id 陣列。")],
    ) -> dict[str, Any]:
        """收件者（to 或 cc）確認這些信。寄件者不能代收。成功後 status=pending 的列表不再包含它們。"""
        agent_id = _agent_id()
        acked = _call(lambda: store.ack(agent_id=agent_id, ids=id))
        return {"acked": acked, "status": "acked"}

    @mcp.tool(structured_output=False)
    def mailbox_get(
        id: Annotated[str, Field(description="msg_ id。")],
    ) -> dict[str, Any]:
        """讀一則自己參與的信（寄件者、to 或 cc）。寄件者用它看對方是否已 ack。"""
        agent_id = _agent_id()
        return _call(lambda: store.get_message(agent_id=agent_id, message_id=id))

    return mcp
