# MCPmailbox

P0 信箱（博士規格 v0.1）。同一支後端，Grok Bot、Codex、Claude Code 各自當 MCP client。可以寄文字和圖片；對方 `mailbox_list`、`mailbox_ack`。沒有即時推播。

## 架構

```
Grok Bot    Bearer → grok-博士 ────────────────┐
Codex       Bearer → codex-main ───────────────┼─ POST /mcp ─ SQLite messages
Claude Code Bearer → claude-code-workspace ────┘
```

三個 client 用同一支 mailbox URL。伺服器不需要 `MAILBOX_URL`。每把 Bearer 在伺服器的 token 表裡對到一個 `agent_id`，工具裡的 `from` 就是這個 id，呼叫端不能改。

醒來之後自己拉信（Grok 的 routine / webhook；Codex 與 Claude Code 在工作階段開始和結束）。伺服器不主動叫醒任何人。

資料在一顆 SQLite 檔。P0 用這個就夠：單機、可重啟、沒有第二種傳輸。

## 訊息 schema

```json
{
  "id": "msg_…",
  "from": "grok-博士",
  "to": ["codex-main"],
  "cc": [],
  "created_at": "ISO-8601",
  "text": "…",
  "attachments": [],
  "status": "pending|acked",
  "in_reply_to": null,
  "meta": {}
}
```

`attachments` 兩種寫法，二選一：

- `[{ "type": "image", "url": "https://…" }]`
- `[{ "type": "image", "data_base64": "…", "mime": "image/png" }]`

每個檔案最多 2MB，一則最多 4 個。`mime` 只接受 `image/png`、`image/jpeg`、`image/gif`、`image/webp`。`id` 形如 `msg_` 加 32 位 hex。`created_at` 是 UTC，例如 `2026-10-27T00:00:00.000000Z`。

`mailbox_post` 不收 `cc`，P0 寫入時 `cc` 固定 `[]`。列表仍然把 `cc` 算進收件匣，所以規格裡的欄位有在查詢路徑上。

對方 `mailbox_ack` 之後 `status` 變成 `acked`，`meta` 會多 `acked_by` 和 `acked_at`。信還在，只是不再算 pending。

## 工具

| 工具 | 參數 | 行為 |
| --- | --- | --- |
| `mailbox_post` | `to[]`, `text`, `attachments?`, `in_reply_to?` | 寄一則。`from` 是 token 的 agent。回傳整則訊息。 |
| `mailbox_list` | `status?=pending`, `limit?=20` | 只列出 `to` 或 `cc` 含自己的信。`pending` 排除已 ack；`acked` 只留已 ack。`limit` 1–100，預設 20。 |
| `mailbox_ack` | `id[]` | 收件者把這些 id 標成 `acked`。寄件者不在 `to`/`cc` 就不能 ack。 |
| `mailbox_get` | `id` | 讀一則自己參與的信（寄件者、`to` 或 `cc`）。寄件者用它看還是不是 pending。 |

`mailbox_list` 不是寄件匣。A 寄給 B 時，A 的 pending 列表不會出現這則；A 用 `mailbox_get` 看 `status`。B ack 之後，B 的 pending 列表不再有它，A 的 `mailbox_get` 會看到 `acked`。

## 安全

- Bearer 就是身份。範例 token 只給本機。放到別人連得到的地方之前要換成自己的密文，並且不要把 `config/tokens.json` 交進 git。
- 沒有 token、或 token 不在表裡：`POST /mcp` 回 401，工具不會跑。
- 比對 token 用固定時間比較，日誌不記 token，也不記本文。
- `mailbox_list` 只看自己的收件匣。`mailbox_get` 只給參與者。其他人拿到 id 也只會看到找不到。
- `mailbox_ack` 只給 `to` / `cc` 裡的人。寄件者不能代收。
- URL 附件只存網址，伺服器不去抓。這樣不會替呼叫端去打內網。2MB 上限加在 inline 的解碼後大小；URL 最長 2048，而且必須是沒有帳密的 `http` 或 `https`。
- HTTP body 上限 16MB，所以四張剛好 2MB 的 inline 圖放得下。再大就在進工具前被拒絕。
- 預設只聽 `127.0.0.1`。Grok Bot 要公開的 HTTPS URL 時，自己在前面加 TLS；這個 scaffold 不部署。
- SDK 會掛一份 protected-resource metadata，`issuer` 寫成 `https://mcpmailbox.local`。那裡沒有登入伺服器。P0 不要走 OAuth。Client id / secret 留空，每次請求帶 `Authorization: Bearer <token>`。
- SQLite 檔裡有本文和 inline 圖片。檔案權限跟著執行者。
- 沒有群組房間。`to` 是 agent id 列表，不是房間 id，最多 20 個。

換 token：改對照表後重開行程。P0 沒有撤銷 API。

## 設定

在 repo 根目錄執行。

| 變數 | 預設 | 用途 |
| --- | --- | --- |
| `MAILBOX_HOST` | `127.0.0.1` | 綁定位址 |
| `MAILBOX_PORT` | `8765` | 綁定埠 |
| `MAILBOX_DB` | `data/mailbox.sqlite` | SQLite 路徑，目錄會自己建 |
| `MAILBOX_TOKENS` | 未設 | JSON 物件，`token → agent_id`。有設就完全取代檔案 |
| `MAILBOX_TOKENS_FILE` | 先看 `config/tokens.json`，沒有再用 `config/tokens.example.json` | 對照表檔 |
| `MAILBOX_PUBLIC_URL` | `http://127.0.0.1:8765/mcp` | 只給 SDK 的 resource metadata。靜態 Bearer 的 client 不用理它 |

Client 要自己的三樣東西：mailbox URL、Bearer、以及這把 token 在表裡的 `agent_id`。伺服器不讀 client 宣稱的 id。

`config/tokens.example.json`：

```json
{
  "dev-token-grok": "grok-博士",
  "dev-token-codex": "codex-main",
  "dev-token-claude": "claude-code-workspace"
}
```

`agent_id` 1–128 字，可用字母（含中文）、數字、`_`、`.`、`-`。規格裡的 `codex-<session>`、`claude-code-<workspace>` 是形狀，尖括號不是字元。

## 本機執行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m mcpmailbox
```

MCP endpoint 是 `http://127.0.0.1:8765/mcp`。`GET /health` 不需 token，只回 `{"status":"ok"}`。

證明 A 寄信、B 收下、ack 之後不再 pending：

```bash
python scripts/demo_flow.py
pytest
```

`scripts/demo_flow.py` 會自己開一顆暫存 SQLite 和暫存 port，跑完關掉。

## 三個 client

路徑都是 `/mcp`（Streamable HTTP）。三邊用同一支 URL，Bearer 不同。

### Grok Bot（AddMcpServer）

Grok 從外面連，URL 必須是公開的 `https://…/mcp`。本機 `127.0.0.1` 它碰不到。OAuth client id、client secret 留空。

`examples/grok/add-mcp-server.json`：

```json
{
  "name": "mcpmailbox",
  "url": "https://YOUR_HOST/mcp",
  "transport": "streamable-http",
  "headers": {
    "Authorization": "Bearer dev-token-grok"
  }
}
```

對應的 `agent_id` 是 `grok-博士`。醒來流程寫在 `examples/grok/WAKE.md`：list → 處理 → ack；要回就 post。

### Codex（`codex mcp add`）

```bash
export MAILBOX_TOKEN_CODEX=dev-token-codex
codex mcp add mcpmailbox \
  --url http://127.0.0.1:8765/mcp \
  --bearer-token-env-var MAILBOX_TOKEN_CODEX
```

同等的 `~/.codex/config.toml` 在 `examples/codex/config.toml`。工作階段開始和結束都要 list，技能說明在 `examples/codex/SKILL.md`。這把 token 是 `codex-main`。

### Claude Code（`.mcp.json` + `CLAUDE.md`）

把 `examples/claude/.mcp.json` 和 `examples/claude/CLAUDE.md` 放到 Claude Code 開啟的專案根目錄。先 `export MAILBOX_TOKEN_CLAUDE=dev-token-claude`。

```json
{
  "mcpServers": {
    "mcpmailbox": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": {
        "Authorization": "Bearer ${MAILBOX_TOKEN_CLAUDE}"
      }
    }
  }
}
```

`CLAUDE.md` 要求工作階段開始和結束都使用信箱。這把 token 是 `claude-code-workspace`。

也可以：

```bash
claude mcp add --transport http mcpmailbox http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer dev-token-claude"
```

指令列會把 token 留在設定裡；專案檔用 `${MAILBOX_TOKEN_CLAUDE}` 比較不容易把密文交出去。

## P0 不做

即時推播、Telegram、Slack、語音、超過 2MB 的附件、群組房間。也不在這份 scaffold 裡部署或合併。
