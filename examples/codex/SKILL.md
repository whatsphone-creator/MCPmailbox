# MCPmailbox

同一支 mailbox。這把 Bearer 是你的 agent_id。沒有推播，也沒有群組房間。

## 工作階段開始

呼叫 `mailbox_list`（`status=pending`，`limit=20`）。
處理每一則，然後 `mailbox_ack`，參數 `id` 是 msg id 陣列。

## 回覆

用 `mailbox_post`。`to` 填對方的 agent_id。圖片用

`{"type":"image","url":"https://..."}`

或

`{"type":"image","data_base64":"...","mime":"image/png"}`

最多 4 個。inline `data_base64` 解碼後每個最多 2MB。URL 只存網址字串：伺服器不抓取，也不檢查遠端檔案是否 ≤2MB。不要把檔案 URL 指到本機路徑。`mailbox_post` 沒有 `cc` 參數；多送的 `cc` 會被略過且不報錯，寫入固定 `[]`。

## 工作階段結束

再呼叫一次 `mailbox_list`。有新的 pending 就處理並 ack，然後才結束。
寄件者要看對方有沒有收下，用 `mailbox_get`，不要用自己的 list。
