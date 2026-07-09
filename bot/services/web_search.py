"""Web Search через DuckDuckGo (бесплатно, без API ключа)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult] = field(default_factory=list)
    error: str = ""


# Попробуем импортировать duckduckgo_search
try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
    logger.warning("duckduckgo_search not installed, falling back to HTTP")


async def web_search(query: str, max_results: int = 5) -> SearchResponse:
    """Поиск в интернете через DuckDuckGo."""
    response = SearchResponse(query=query)

    try:
        if HAS_DDGS:
            import asyncio
            loop = asyncio.get_event_loop()

            def _search():
                with DDGS() as ddgs:
                    raw = list(
                        ddgs.text(
                            query,
                            max_results=max_results,
                            region="wt-wt",
                        )
                    )
                    results = []
                    for r in raw:
                        results.append(SearchResult(
                            title=r.get("title", ""),
                            url=r.get("href", ""),
                            snippet=r.get("body", ""),
                        ))
                    return results

            response.results = await loop.run_in_executor(None, _search)
        else:
            # Fallback: HTTP запрос к DuckDuckGo HTML
            import requests
            from bs4 import BeautifulSoup

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            r = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers=headers,
                timeout=10,
            )
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select(".result__a")[:max_results]:
                title = a.get_text(strip=True)
                url = a.get("href", "")
                # Ищем сниппет
                parent = a.find_parent("div", class_="result")
                snippet = ""
                if parent:
                    snip_el = parent.select_one(".result__snippet")
                    if snip_el:
                        snippet = snip_el.get_text(strip=True)
                response.results.append(SearchResult(
                    title=title, url=url, snippet=snippet,
                ))

    except Exception as e:
        logger.error("Web search failed: %s", e)
        response.error = str(e)

    return response


def format_search_results(response: SearchResponse, max_results: int = 5) -> str:
    """Отформатировать результаты поиска в текст."""
    if response.error:
        return f"🔍 Search error: {response.error}"

    if not response.results:
        return f"🔍 No results for: _{response.query}_"

    lines = [f"🔍 **Search: {response.query}**\n"]
    for i, r in enumerate(response.results[:max_results], 1):
        lines.append(f"{i}. **[{r.title}]({r.url})**")
        if r.snippet:
            lines.append(f"   {r.snippet[:200]}")
        lines.append("")

    return "\n".join(lines)
