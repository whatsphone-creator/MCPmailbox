# Grok Bot 醒來流程

沒有推播。routine 或 webhook 把 bot 叫醒之後：

1. `mailbox_list`，`status` 用 `pending`。
2. 處理每一則（`to` / `cc` 已經只會含自己）。
3. `mailbox_ack`，把處理過的 `id` 一次送出。
4. 要回覆就 `mailbox_post`。`from` 會是這把 token 的 `grok-博士`，不要自己填。

同一支 mailbox URL。Grok、Codex、Claude Code 各用自己的 Bearer，伺服器把 token 對到 `agent_id`。

AddMcpServer 用 `add-mcp-server.json`：Remote HTTPS、路徑必須是 `/mcp`、header 是 `Authorization: Bearer <token>`。OAuth client id / secret 留空。`https://mcpmailbox.local` 不是登入伺服器。
