"""The Graph calls this needs, and no more.

Five of them: read the media somebody mentioned us on, read the comment that did
it, put a username to an id, say "saved", and refresh the token before it lapses.

Two habits worth naming, because both are easy to get wrong and neither errors
when you do. The access token goes in an `Authorization` header rather than
`?access_token=`, so it does not land in a reverse proxy's access log. And every
call carries `appsecret_proof`, so a token lifted from somewhere else is not on
its own enough to use.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.instagram import signature
from backend.runtime.http import _client

log = logging.getLogger(__name__)

GRAPH = "https://graph.instagram.com/v23.0"

#: What a mention is worth reading for. `caption` and `permalink` are the two
#: that make the mention route worth preferring over a direct message at all.
MEDIA_FIELDS = (
    "id,caption,permalink,media_type,media_url,thumbnail_url,timestamp,username,owner"
)


class InstagramError(RuntimeError):
    """Graph refused. Carries the message Graph gave, which is the only useful part."""


class InstagramClient:
    def __init__(self, token: str | None = None, *, timeout: float = 30.0):
        self.token = token or signature.access_token()
        self.timeout = timeout

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(extra or {})
        if self.token:
            proof = signature.appsecret_proof(self.token)
            if proof:
                params["appsecret_proof"] = proof
        return params

    async def _call(
        self, method: str, path: str, *, params: dict | None = None, body: dict | None = None
    ) -> dict[str, Any]:
        if not self.token:
            raise InstagramError("no Instagram access token is stored")
        try:
            response = await _client(self.timeout).request(
                method,
                f"{GRAPH}{path}",
                headers={"Authorization": f"Bearer {self.token}"},
                params=self._params(params),
                json=body,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise InstagramError(f"Instagram could not be reached: {exc}") from exc

        if response.status_code >= 400:
            detail = ""
            try:
                detail = (response.json().get("error") or {}).get("message") or ""
            except ValueError:
                detail = response.text[:200]
            if response.status_code in (400, 401, 403) and "token" in detail.lower():
                detail += ". Reconnect Instagram in Settings."
            raise InstagramError(f"Instagram returned HTTP {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise InstagramError("Instagram returned something that was not JSON") from exc

    async def mentioned_media(self, ig_user_id: str, media_id: str) -> dict[str, Any]:
        """The post somebody @mentioned this account on.

        This is the call that makes the mention route worth having: it returns
        the permalink and the caption, neither of which a direct-message share
        carries.
        """
        return await self._call(
            "GET",
            f"/{ig_user_id}",
            params={"fields": f"mentioned_media.media_id({media_id}){{{MEDIA_FIELDS}}}"},
        )

    async def media(self, media_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/{media_id}", params={"fields": MEDIA_FIELDS})

    async def comment(self, comment_id: str) -> dict[str, Any]:
        return await self._call(
            "GET", f"/{comment_id}", params={"fields": "id,text,timestamp,username,from"}
        )

    async def profile(self, igsid: str) -> dict[str, Any]:
        """Who an opaque sender id belongs to, so a person can decide about them."""
        return await self._call("GET", f"/{igsid}", params={"fields": "name,username"})

    async def send_text(self, recipient_id: str, text: str) -> dict[str, Any]:
        return await self._call(
            "POST",
            "/me/messages",
            body={"recipient": {"id": recipient_id}, "message": {"text": text[:900]}},
        )

    async def refresh_token(self) -> tuple[str, int]:
        """A fresh 60 days. Only works while the current token is still valid."""
        data = await self._call(
            "GET", "/refresh_access_token", params={"grant_type": "ig_refresh_token"}
        )
        token = data.get("access_token")
        if not token:
            raise InstagramError("Instagram did not return a refreshed token")
        return token, int(data.get("expires_in") or 0)


def unwrap_mentioned_media(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull the media out of the nested shape `mentioned_media` comes back in."""
    media = payload.get("mentioned_media")
    if isinstance(media, dict):
        return media
    if isinstance(media, list) and media:
        return media[0]
    return payload if payload.get("permalink") or payload.get("caption") else {}
