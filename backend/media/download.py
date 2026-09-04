"""Fetching a file somebody else's payload named.

The URLs handled here arrive inside a webhook, so they are attacker-influenced
even when the signature says the delivery is genuine. Two guards, and the second
is the one that closes the class outright:

* `check_url_async` on **every** redirect hop, the same discipline
  `backend/web/reader.py` uses -- validating only the first address and then
  following redirects is how a public URL becomes a request to 169.254.169.254.
* a hostname allowlist. Nothing Instagram serves lives outside these four
  domains, so anything else is refused without needing to reason about it.

The size cap is enforced **during** the stream rather than from `content-length`,
because a server can omit that header or lie about it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from backend.mcp.ssrf import UnsafeURL, check_url_async
from backend.runtime.http import _client

log = logging.getLogger(__name__)

ALLOWED_HOSTS = ("fbsbx.com", "cdninstagram.com", "fbcdn.net", "instagram.com")
MAX_REDIRECTS = 5
CHUNK = 64 * 1024


class DownloadError(RuntimeError):
    """The file could not be fetched. Carries a sentence fit to show someone."""


def _host_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_HOSTS)


async def fetch_to(
    url: str,
    destination: Path,
    *,
    token: str | None = None,
    max_bytes: int,
    timeout: float = 120.0,
) -> Path:
    """Stream a URL to a file, or raise with the reason it did not arrive."""
    if not url:
        raise DownloadError("there was no address to fetch")

    headers = {"User-Agent": "PSOK/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    current = url
    destination.parent.mkdir(parents=True, exist_ok=True)
    client = _client(timeout)

    for _ in range(MAX_REDIRECTS + 1):
        if not _host_allowed(current):
            raise DownloadError(f"'{urlparse(current).hostname}' is not an Instagram address")
        try:
            await check_url_async(current)
        except UnsafeURL as exc:
            raise DownloadError(str(exc)) from exc

        try:
            async with client.stream(
                "GET", current, headers=headers, timeout=timeout, follow_redirects=False
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise DownloadError(f"{current} redirected to nowhere")
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    # An expired lookaside asset answers 403. That is terminal,
                    # not transient: the bytes are gone and retrying proves it
                    # three more times.
                    raise DownloadError(
                        f"Instagram returned HTTP {response.status_code} for this file"
                    )

                written = 0
                with destination.open("wb") as handle:
                    async for chunk in response.aiter_bytes(CHUNK):
                        written += len(chunk)
                        if written > max_bytes:
                            handle.close()
                            destination.unlink(missing_ok=True)
                            raise DownloadError(
                                f"the file is larger than the {max_bytes // (1024 * 1024)}MB limit"
                            )
                        handle.write(chunk)
                if not written:
                    destination.unlink(missing_ok=True)
                    raise DownloadError("the file came back empty")
                return destination
        except httpx.HTTPError as exc:
            destination.unlink(missing_ok=True)
            raise DownloadError(f"the file could not be fetched: {exc}") from exc

    raise DownloadError(f"{url} redirected more than {MAX_REDIRECTS} times")
