"""SQLite persistence for P0 messages."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcpmailbox.errors import MailboxError
from mcpmailbox.validate import (
    MAX_ACK_IDS,
    normalize_attachments,
    normalize_message_id,
    normalize_recipients,
    normalize_text,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    to_json TEXT NOT NULL,
    cc_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL,
    attachments_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'acked')),
    in_reply_to TEXT,
    meta_json TEXT NOT NULL,
    acked_at TEXT,
    acked_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_status_created
    ON messages (status, created_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_id() -> str:
    return f"msg_{uuid.uuid4().hex}"


def public_message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "from": row["sender"],
        "to": json.loads(row["to_json"]),
        "cc": json.loads(row["cc_json"]),
        "created_at": row["created_at"],
        "text": row["body"],
        "attachments": json.loads(row["attachments_json"]),
        "status": row["status"],
        "in_reply_to": row["in_reply_to"],
        "meta": json.loads(row["meta_json"]),
    }


def _addresses(row: sqlite3.Row) -> tuple[list[str], list[str]]:
    return json.loads(row["to_json"]), json.loads(row["cc_json"])


def _is_recipient(row: sqlite3.Row, agent_id: str) -> bool:
    to, cc = _addresses(row)
    return agent_id in to or agent_id in cc


def _is_participant(row: sqlite3.Row, agent_id: str) -> bool:
    return row["sender"] == agent_id or _is_recipient(row, agent_id)


class MailboxStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _get_row(self, conn: sqlite3.Connection, message_id: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()

    def post(
        self,
        *,
        sender: str,
        to: list[str],
        text: str,
        attachments: list[Any] | None,
        in_reply_to: str | None,
    ) -> dict[str, Any]:
        recipients = normalize_recipients(to)
        stored_attachments = normalize_attachments(attachments)
        body = normalize_text(text, has_attachments=bool(stored_attachments))
        reply_to = None if in_reply_to is None else normalize_message_id(in_reply_to, field="in_reply_to")
        message_id = _new_id()
        created_at = _now()
        with self._connect() as conn:
            if reply_to is not None:
                parent = self._get_row(conn, reply_to)
                if parent is None or not _is_participant(parent, sender):
                    raise MailboxError("in_reply_to does not match a message you can see")
            conn.execute(
                """
                INSERT INTO messages (
                    id, sender, to_json, cc_json, created_at, body,
                    attachments_json, status, in_reply_to, meta_json
                ) VALUES (?, ?, ?, '[]', ?, ?, ?, 'pending', ?, '{}')
                """,
                (
                    message_id,
                    sender,
                    json.dumps(recipients, ensure_ascii=False),
                    created_at,
                    body,
                    json.dumps(stored_attachments, ensure_ascii=False),
                    reply_to,
                ),
            )
            row = self._get_row(conn, message_id)
        assert row is not None
        return public_message(row)

    def list_messages(self, *, agent_id: str, status: str, limit: int) -> list[dict[str, Any]]:
        if status not in {"pending", "acked"}:
            raise MailboxError("status must be pending or acked")
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise MailboxError("limit must be an integer from 1 to 100")
        query = """
            SELECT messages.* FROM messages
            WHERE messages.status = ?
              AND (
                EXISTS (
                    SELECT 1 FROM json_each(messages.to_json)
                    WHERE json_each.value = ?
                )
                OR EXISTS (
                    SELECT 1 FROM json_each(messages.cc_json)
                    WHERE json_each.value = ?
                )
              )
            ORDER BY messages.created_at DESC, messages.id DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(query, (status, agent_id, agent_id, limit)).fetchall()
        return [public_message(row) for row in rows]

    def get_message(self, *, agent_id: str, message_id: str) -> dict[str, Any]:
        message_id = normalize_message_id(message_id, field="id")
        with self._connect() as conn:
            row = self._get_row(conn, message_id)
            if row is None or not _is_participant(row, agent_id):
                raise MailboxError("message not found")
            return public_message(row)

    def ack(self, *, agent_id: str, ids: list[str]) -> list[str]:
        if not isinstance(ids, list) or not ids:
            raise MailboxError("id must be a non-empty list of message ids")
        if len(ids) > MAX_ACK_IDS:
            raise MailboxError(f"id accepts at most {MAX_ACK_IDS} message ids")
        cleaned = [normalize_message_id(item, field="id") for item in ids]
        if len(set(cleaned)) != len(cleaned):
            raise MailboxError("id contains a duplicate")
        acked_at = _now()
        with self._connect() as conn:
            rows: list[sqlite3.Row] = []
            for message_id in cleaned:
                row = self._get_row(conn, message_id)
                if row is None or not _is_recipient(row, agent_id):
                    raise MailboxError("message not found or not addressed to you")
                rows.append(row)
            for row in rows:
                if row["status"] == "acked":
                    continue
                meta = json.loads(row["meta_json"])
                meta["acked_by"] = agent_id
                meta["acked_at"] = acked_at
                conn.execute(
                    """
                    UPDATE messages
                    SET status = 'acked', acked_by = ?, acked_at = ?, meta_json = ?
                    WHERE id = ?
                    """,
                    (
                        agent_id,
                        acked_at,
                        json.dumps(meta, ensure_ascii=False),
                        row["id"],
                    ),
                )
        return cleaned
