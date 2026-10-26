"""Static Bearer token → agent_id. P0 does not issue OAuth tokens."""

from __future__ import annotations

import hmac

from mcp.server.auth.provider import AccessToken, TokenVerifier

MAILBOX_SCOPE = "mailbox"


class StaticTokenVerifier(TokenVerifier):
    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = dict(tokens)

    async def verify_token(self, token: str) -> AccessToken | None:
        presented = token.encode("utf-8")
        agent_id: str | None = None
        for known, candidate in self._tokens.items():
            known_b = known.encode("utf-8")
            if len(known_b) == len(presented) and hmac.compare_digest(known_b, presented):
                agent_id = candidate
        if agent_id is None:
            return None
        return AccessToken(
            token=token,
            client_id=agent_id,
            scopes=[MAILBOX_SCOPE],
        )
