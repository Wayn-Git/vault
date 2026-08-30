"""Reading the open web.

PSOK could reach the web only through a connector before this: the model had no
way to look something up unless the user had switched one on, which made
"search for X" fail for a reason that had nothing to do with the request. These
two tools are read-only and touch nothing on the machine, so they carry the
same low risk as reading an indexed document.

Search goes through DuckDuckGo's HTML endpoint, which needs no API key. That is
a deliberate trade: no key to configure, at the cost of a result page whose
markup is not a contract. When parsing finds nothing, the tool says so plainly
rather than returning an empty list that reads like "no results".
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

from backend.mcp.ssrf import UnsafeURL, check_url
from backend.tools.base import RiskLevel, Tool, ToolContext, ToolResult

SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"
USER_AGENT = "Mozilla/5.0 (compatible; PSOK/0.1; +https://github.com/)"
MAX_PAGE_BYTES = 2_000_000

_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'(?:.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>)?',
    re.DOTALL,
)
_TAGS = re.compile(r"<[^>]+>")


def _clean(fragment: str | None) -> str:
    if not fragment:
        return ""
    return html.unescape(_TAGS.sub("", fragment)).strip()


def _real_url(href: str) -> str:
    """DuckDuckGo wraps results in a redirect; the destination is in `uddg`."""
    if href.startswith("//"):
        href = f"https:{href}"
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


async def search_web(args: dict[str, Any], _: ToolContext) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult.error("search_web needs a query")
    limit = max(1, min(int(args.get("limit") or 6), 15))

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            response = await client.get(
                SEARCH_URL.format(query=quote_plus(query)),
                headers={"User-Agent": USER_AGENT},
            )
    except httpx.HTTPError as exc:
        return ToolResult.error(f"the search request failed: {exc}")

    if response.status_code != 200:
        return ToolResult.error(f"the search endpoint returned HTTP {response.status_code}")

    hits = []
    for match in _RESULT.finditer(response.text):
        title = _clean(match.group("title"))
        url = _real_url(match.group("href"))
        snippet = _clean(match.group("snippet"))
        if not title or not url:
            continue
        hits.append(f"{title}\n{url}" + (f"\n{snippet}" if snippet else ""))
        if len(hits) >= limit:
            break

    if not hits:
        return ToolResult.ok(
            f"No results came back for {query!r}. The search page may have changed shape;"
            " fetch_url on a specific address still works."
        )
    return ToolResult.ok("\n\n".join(hits))


async def fetch_url(args: dict[str, Any], _: ToolContext) -> ToolResult:
    url = (args.get("url") or "").strip()
    if not url:
        return ToolResult.error("fetch_url needs a url")
    try:
        # The same guard the MCP transports use: a URL that resolves to a
        # private address is not fetched just because a model asked for it.
        check_url(url)
    except UnsafeURL as exc:
        return ToolResult.error(str(exc))

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=25.0) as client:
            response = await client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        return ToolResult.error(f"could not fetch {url}: {exc}")

    if response.status_code >= 400:
        return ToolResult.error(f"{url} returned HTTP {response.status_code}")

    body = response.text[:MAX_PAGE_BYTES]
    kind = response.headers.get("content-type", "")
    if "html" in kind:
        body = _readable(body)
    return ToolResult.ok(body)


_SCRIPTS = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_BLOCK_END = re.compile(r"</(p|div|section|article|li|h[1-6]|tr)>", re.IGNORECASE)


def _readable(page: str) -> str:
    """Strip a page down to its text, keeping line structure."""
    text = _SCRIPTS.sub(" ", page)
    text = _BLOCK_END.sub("\n", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAGS.sub("", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def tools() -> list[Tool]:
    return [
        Tool(
            name="search_web",
            description=(
                "Search the web and return the top results with their URLs. Use this"
                " when the answer is not on the user's machine and not in their notes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "limit": {"type": "integer", "description": "Maximum results (default 6)"},
                },
                "required": ["query"],
            },
            handler=search_web,
            risk=RiskLevel.LOW,
        ),
        Tool(
            name="fetch_url",
            description=(
                "Fetch a web page or file and return its text. HTML is reduced to"
                " readable text. Use after search_web, or when the user gives a URL."
            ),
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string", "description": "The address to fetch"}},
                "required": ["url"],
            },
            handler=fetch_url,
            risk=RiskLevel.LOW,
        ),
    ]
