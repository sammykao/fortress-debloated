"""Search provider settings used by the browser service."""

from typing import NamedTuple


class SearchProvider(NamedTuple):
    url: str
    result_selector: str
    extract_script: str
    throttle_statuses: tuple[int, ...]


DUCKDUCKGO = SearchProvider(
    url="https://html.duckduckgo.com/html/",
    result_selector=".result",
    extract_script="""nodes => nodes.map((node, index) => {
        const link = node.querySelector('.result__a');
        if (!link) return null;
        const snippet = node.querySelector('.result__snippet');
        const url = new URL(link.href).searchParams.get('uddg') || link.href;
        if (!/^https?:\\/\\//.test(url)) return null;
        return {title: link.textContent.trim(), url,
            snippet: snippet?.textContent.trim() || '', rank: index + 1};
    }).filter(Boolean)""",
    throttle_statuses=(202, 403, 429),
)
