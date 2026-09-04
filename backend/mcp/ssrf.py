"""URL safety for remote MCP transports (ADR-0007).

Applied at transport construction, so a blocked URL never opens a connection.
The point is not distrust of the user's own config -- it is that a mistyped or
hijacked URL must not be able to reach services on the local network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURL(ValueError):
    pass


def _is_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise UnsafeURL(f"cannot resolve host '{host}': {exc}") from exc

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def check_url(url: str, *, allow_local: bool = False) -> None:
    """Raise UnsafeURL unless this URL is safe to connect to.

    allow_local exists because a locally hosted MCP server on localhost is a
    legitimate and common setup; it must be opted into explicitly per server.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURL(f"scheme '{parsed.scheme}' is not allowed; use http or https")
    if not parsed.hostname:
        raise UnsafeURL(f"no host in URL '{url}'")
    if allow_local:
        return
    if _is_private(parsed.hostname):
        raise UnsafeURL(
            f"'{parsed.hostname}' resolves to a private or loopback address."
            " Set allow_local: true on this server if that is intended."
        )


async def check_url_async(url: str, *, allow_local: bool = False) -> None:
    """check_url with the name resolution off the event loop.

    `getaddrinfo` blocks, and this runs before every remote connect -- on a slow
    or failing resolver it stalled the whole process, streaming turns included,
    which surfaced in the interface as an unexplained network error.
    """
    await asyncio.to_thread(check_url, url, allow_local=allow_local)
