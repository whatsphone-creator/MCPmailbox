import json

from mcpmailbox.store import MailboxStore


def test_unicode_agent_id_is_visible_in_the_inbox(tmp_path) -> None:
    store = MailboxStore(tmp_path / "unicode.sqlite")
    store.migrate()
    message = store.post(
        sender="codex-main",
        to=["grok-博士"],
        text="給博士",
        attachments=None,
        in_reply_to=None,
    )
    listed = store.list_messages(agent_id="grok-博士", status="pending", limit=20)
    assert [item["id"] for item in listed] == [message["id"]]
    assert listed[0]["from"] == "codex-main"
    assert listed[0]["to"] == ["grok-博士"]


def test_cc_is_part_of_the_inbox_and_ack_hides_pending(tmp_path) -> None:
    store = MailboxStore(tmp_path / "mailbox.sqlite")
    store.migrate()
    message = store.post(
        sender="grok-博士",
        to=["codex-main"],
        text="hello",
        attachments=[{"type": "image", "url": "https://example.com/a.png"}],
        in_reply_to=None,
    )
    with store._connect() as conn:
        conn.execute(
            "UPDATE messages SET to_json = '[]', cc_json = ? WHERE id = ?",
            (json.dumps(["codex-main"]), message["id"]),
        )

    pending = store.list_messages(agent_id="codex-main", status="pending", limit=20)
    assert [item["id"] for item in pending] == [message["id"]]
    assert store.list_messages(agent_id="grok-博士", status="pending", limit=20) == []

    store.ack(agent_id="codex-main", ids=[message["id"]])
    assert store.list_messages(agent_id="codex-main", status="pending", limit=20) == []
    acked = store.get_message(agent_id="grok-博士", message_id=message["id"])
    assert acked["status"] == "acked"
    assert acked["meta"]["acked_by"] == "codex-main"
    assert acked["cc"] == ["codex-main"]
