"""Run the mailbox MCP server over Streamable HTTP."""

from __future__ import annotations

from mcpmailbox.config import load_settings
from mcpmailbox.server import MAX_HTTP_BODY, build_server


def main() -> None:
    settings = load_settings()
    server = build_server(settings)
    server.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        json_response=True,
        stateless_http=False,
        max_request_body_size=MAX_HTTP_BODY,
    )


if __name__ == "__main__":
    main()
