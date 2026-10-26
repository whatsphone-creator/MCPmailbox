# 信箱是必用工具

這個工作區連著 MCPmailbox。Bearer 決定你的 agent_id（範例是 `claude-code-workspace`）。沒有推播。

工作階段一開始就呼叫 `mailbox_list`（`status` 預設 `pending`）。處理完呼叫 `mailbox_ack`，`id` 是訊息 id 陣列。要回别人用 `mailbox_post`。工作階段結束前再 list 一次。

`mailbox_list` 只含 `to` 或 `cc` 有自己的信。自己寄出的信用 `mailbox_get` 看 `status` 是 `pending` 還是 `acked`。

不要改走 Telegram、Slack、語音，也不要假設有群組房間或即時通知。圖片最多 4 個，每個最多 2MB。
