import re
from html.parser import HTMLParser


_MEDIA_RE = re.compile(
    r"""(?P<url>https?://[^\s"'<>]+?\.(?:m3u8|mp4|mp3|m4a|wav)(?:\?[^\s"'<>]*)?)""",
    re.IGNORECASE,
)


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and not self.title:
            self.title = data.strip()


def extract_title(html: str) -> str:
    parser = _TitleParser()
    try:
        parser.feed(html)
    except Exception:
        return ""
    return parser.title


def extract_media_urls(text: str) -> list[str]:
    found: list[str] = []
    for match in _MEDIA_RE.finditer(text):
        url = match.group("url")
        if url not in found:
            found.append(url)
    return found
