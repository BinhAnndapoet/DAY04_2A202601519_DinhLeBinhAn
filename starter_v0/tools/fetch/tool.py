from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

import requests

from tools._shared import domain, err

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class _TextExtractor(HTMLParser):
    """Trích text thuần từ HTML, bỏ script/style/nav/footer."""

    _SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg", "iframe"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []
        self.title = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    @property
    def text(self) -> str:
        return " ".join(self._chunks)


def read_url(url: str = "") -> dict[str, Any]:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml,*/*"},
            timeout=30,
        )
        response.raise_for_status()
        final_url = response.url or url

        parser = _TextExtractor()
        parser.feed(response.text)
        if parser.title:
            title = parser.title
        else:
            # Fallback: thẻ <title>...</title>
            m = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.I | re.S)
            title = (m.group(1).strip() if m else url)

        return {
            "tool": "read_url",
            "url": final_url,
            "items": [
                {
                    "title": title,
                    "url": final_url,
                    "source": domain(final_url),
                    "summary": parser.text[:4000],
                }
            ],
        }
    except Exception as exc:
        return err("read_url", exc)
