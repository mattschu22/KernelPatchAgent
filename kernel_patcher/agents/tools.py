"""Custom tools for kernel patcher agents."""

from __future__ import annotations

import urllib.parse

import httpx
from agents.tool import WebSearchTool, WebSearchToolFilters, function_tool

BOOTLIN_BASE = "https://elixir.bootlin.com"
BOOTLIN_TRUNCATE_LIMIT = 20_000


def build_bootlin_fetch_tool():
    """Build the fetch_bootlin tool for the Elixir agent."""

    @function_tool(
        name_override="fetch_bootlin",
        description_override=(
            "Fetch content from elixir.bootlin.com. "
            "Provide a path like /linux/v5.10.224/source/kernel/ptrace.c"
        ),
    )
    async def fetch_bootlin(path: str) -> str:
        url = urllib.parse.urljoin(BOOTLIN_BASE, path)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text

        if len(text) > BOOTLIN_TRUNCATE_LIMIT:
            text = text[:BOOTLIN_TRUNCATE_LIMIT] + "\n\n[truncated output]"
        return text

    return fetch_bootlin


def build_kernel_org_search_tool():
    """Build a web search tool restricted to kernel.org."""
    return WebSearchTool(
        filters=WebSearchToolFilters(allowed_domains=["kernel.org"]),
        search_context_size="low",
    )
