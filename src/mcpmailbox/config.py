"""Process configuration. Clients use URL + Bearer; the server maps Bearer → agent_id."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from mcpmailbox.validate import require_agent_id


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: Path
    tokens: dict[str, str]
    public_url: str


def _load_token_map(raw: str, *, source: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{source} is not a JSON object of token → agent_id") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise SystemExit(f"{source} must be a non-empty JSON object of token → agent_id")
    tokens: dict[str, str] = {}
    for token, agent_id in parsed.items():
        if not isinstance(token, str) or token.strip() == "" or token != token.strip():
            raise SystemExit(f"{source} has an empty or padded token key")
        if not isinstance(agent_id, str):
            raise SystemExit(f"{source} agent_id for a token must be a string")
        try:
            tokens[token] = require_agent_id(agent_id, field="agent_id")
        except Exception as exc:
            raise SystemExit(f"{source}: {exc}") from exc
    return tokens


def _tokens_from_env_or_file() -> dict[str, str]:
    inline = os.environ.get("MAILBOX_TOKENS")
    if inline is not None and inline.strip() != "":
        return _load_token_map(inline, source="MAILBOX_TOKENS")

    configured = os.environ.get("MAILBOX_TOKENS_FILE")
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise SystemExit(f"MAILBOX_TOKENS_FILE does not exist: {path}")
        return _load_token_map(path.read_text(encoding="utf-8"), source=str(path))

    local = Path("config/tokens.json")
    example = Path("config/tokens.example.json")
    if local.is_file():
        return _load_token_map(local.read_text(encoding="utf-8"), source=str(local))
    if example.is_file():
        return _load_token_map(example.read_text(encoding="utf-8"), source=str(example))
    raise SystemExit(
        "No token map. Set MAILBOX_TOKENS or MAILBOX_TOKENS_FILE, "
        "or add config/tokens.json (see config/tokens.example.json)."
    )


def load_settings() -> Settings:
    host = os.environ.get("MAILBOX_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port_raw = os.environ.get("MAILBOX_PORT", "8765")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise SystemExit("MAILBOX_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("MAILBOX_PORT must be between 1 and 65535")

    db_path = Path(os.environ.get("MAILBOX_DB", "data/mailbox.sqlite"))
    public_host = "127.0.0.1" if host in {"0.0.0.0", "::", "::0"} else host
    default_public = f"http://{public_host}:{port}/mcp"
    public_url = os.environ.get("MAILBOX_PUBLIC_URL", default_public).strip() or default_public
    if not public_url.startswith(("http://", "https://")):
        raise SystemExit("MAILBOX_PUBLIC_URL must be an http(s) URL")

    return Settings(
        host=host,
        port=port,
        db_path=db_path,
        tokens=_tokens_from_env_or_file(),
        public_url=public_url,
    )
