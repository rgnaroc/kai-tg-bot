"""Web Search через DuckDuckGo HTML (бесплатно, без API ключа, без внешних зависимостей).

Использует httpx (уже есть в проекте) и парсит HTML без bs4.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

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


def _extract_results(html: str) -> list[SearchResult]:
    """Извлечь результаты из HTML DuckDuckGo без bs4."""
    results = []

    # Ищем блоки .result__a — ссылки результатов
    # Структура: <a rel="nofollow" class="result__a" href="...">Title</a>
    # После ссылки: <a class="result__snippet" ...>snippet</a>

    # Разбиваем по result__a
    parts = html.split('class="result__a"')
    for part in parts[1:]:  # Первый элемент — до первого результата
        # Извлекаем href
        href_match = re.search(r'href="([^"]+)"', part)
        if not href_match:
            continue
        url = href_match.group(1)

        # Извлекаем title (текст между </a> и следующим тегом или до конца)
        title_match = re.search(r'>([^<]+)</a>', part)
        title = title_match.group(1).strip() if title_match else ""

        # Извлекаем snippet
        snippet = ""
        snip_match = re.search(r'class="result__snippet"[^>]*>([^<]+)', part)
        if snip_match:
            snippet = snip_match.group(1).strip()

        if title and url:
            # DuckDuckGo оборачивает URL в редирект — декодируем
            if "uddg=" in url:
                from urllib.parse import unquote, parse_qs, urlparse
                try:
                    parsed = urlparse(url)
                    qs = parse_qs(parsed.query)
                    if "uddg" in qs:
                        url = unquote(qs["uddg"][0])
                except Exception:
                    pass
            results.append(SearchResult(title=title, url=url, snippet=snippet))

    return results


async def web_search(query: str, max_results: int = 5) -> SearchResponse:
    """Поиск в интернете через DuckDuckGo HTML."""
    response = SearchResponse(query=query)

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        }

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers=headers,
            )

        if r.status_code != 200:
            response.error = f"DuckDuckGo returned status {r.status_code}"
            return response

        results = _extract_results(r.text)
        response.results = results[:max_results]

    except httpx.TimeoutException:
        response.error = "Search request timed out"
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
        lines.append(f"{i}. **{r.title}**")
        if r.snippet:
            lines.append(f"   {r.snippet[:200]}")
        lines.append(f"   [{r.url}]({r.url})")
        lines.append("")

    return "\n".join(lines)
