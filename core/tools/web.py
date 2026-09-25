"""Web research tools: search the internet and read web pages (with safety checks)."""
from __future__ import annotations

import html
import ipaddress
import os
import re
import socket
import urllib.parse
from html.parser import HTMLParser

from core.tools.registry import ToolResult, tool

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
MAX_BYTES = 2_000_000


# ------------------------------------------------------------------ search backends
def _tavily(query: str, n: int) -> list[dict]:
    import requests
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY not set")
    r = requests.post("https://api.tavily.com/search", timeout=20,
                      json={"api_key": key, "query": query, "max_results": n})
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")[:300]}
            for x in r.json().get("results", [])]


def _ddg_url(href: str) -> str:
    """DuckDuckGo wraps result links as //duckduckgo.com/l/?uddg=<real url>."""
    href = html.unescape(href)
    if "uddg=" in href:
        return urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query)["uddg"][0])
    return "https:" + href if href.startswith("//") else href


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_ddg_html(page: str, n: int) -> list[dict]:
    results = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)',
                         page, re.S):
        snip = re.search(r'class="result__snippet"[^>]*>(.*?)</(?:a|div|td)>', m.group(3), re.S)
        url = _ddg_url(m.group(1))
        if "duckduckgo.com/y.js" in url:  # ads
            continue
        results.append({"title": _strip_tags(m.group(2)), "url": url,
                        "snippet": _strip_tags(snip.group(1)) if snip else ""})
        if len(results) >= n:
            break
    return results


def parse_ddg_lite(page: str, n: int) -> list[dict]:
    results = []
    links = list(re.finditer(r"<a[^>]+href=\"([^\"]+)\"[^>]+class=['\"]result-link['\"][^>]*>(.*?)</a>", page, re.S))
    snippets = re.findall(r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", page, re.S)
    for i, m in enumerate(links[:n]):
        results.append({"title": _strip_tags(m.group(2)), "url": _ddg_url(m.group(1)),
                        "snippet": _strip_tags(snippets[i]) if i < len(snippets) else ""})
    return results


def _duckduckgo(query: str, n: int) -> list[dict]:
    import requests
    headers = {"User-Agent": UA}
    r = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=headers, timeout=20)
    results = parse_ddg_html(r.text, n) if r.ok else []
    if not results:
        r = requests.get("https://lite.duckduckgo.com/lite/", params={"q": query}, headers=headers, timeout=20)
        results = parse_ddg_lite(r.text, n) if r.ok else []
    if not results:
        raise RuntimeError(f"DuckDuckGo returned no results (HTTP {r.status_code})")
    return results


def _wikipedia(query: str, n: int) -> list[dict]:
    import requests
    r = requests.get("https://en.wikipedia.org/w/api.php", headers={"User-Agent": "OmniPilot/1.0"}, timeout=20,
                     params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": n})
    r.raise_for_status()
    return [{"title": x["title"], "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(x["title"].replace(" ", "_")),
             "snippet": _strip_tags(x.get("snippet", ""))} for x in r.json()["query"]["search"]]


SEARCH_BACKENDS = [("tavily", _tavily), ("duckduckgo", _duckduckgo), ("wikipedia", _wikipedia)]


@tool("web_search",
      "Search the internet for current information (news, prices, docs, facts after your training). "
      "Returns titles, URLs and snippets. Then use read_webpage on the best URLs and cite them as sources.",
      {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}},
      ["query"])
def web_search(ctx, query, max_results=5):
    n = max(1, min(int(max_results), 8))
    errors = []
    for name, backend in SEARCH_BACKENDS:
        try:
            results = backend(query, n)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {str(e)[:120]}")
            continue
        if results:
            lines = [f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet'][:300]}" for i, r in enumerate(results, 1)]
            return ToolResult(True, f"Results from {name} for '{query}':\n" + "\n".join(lines))
    return ToolResult(False, "Search failed: " + " | ".join(errors))


# ------------------------------------------------------------------ reading pages
def check_url(url: str) -> str:
    """Allow only public http(s) addresses (blocks localhost, private networks and cloud metadata)."""
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Only http(s) URLs are allowed")
    for info in socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)):
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise ValueError(f"Blocked for safety: {parts.hostname} is not a public address")
    return url


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "iframe"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3"):
            self.parts.append("## ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(page: str) -> tuple[str, str]:
    p = _TextExtractor()
    p.feed(page)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return p.title.strip(), text


def fetch(url: str, max_redirects: int = 3):
    import requests
    for _ in range(max_redirects + 1):
        check_url(url)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=False, stream=True)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            url = urllib.parse.urljoin(url, r.headers.get("location", ""))
            continue
        data = r.raw.read(MAX_BYTES + 1, decode_content=True)
        return r, data[:MAX_BYTES], url
    raise ValueError("Too many redirects")


def _encoding(r, data: bytes) -> str:
    if "charset=" in r.headers.get("content-type", "").lower():
        return r.encoding or "utf-8"
    m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', data[:4000], re.I)
    return m.group(1).decode() if m else "utf-8"


@tool("read_webpage",
      "Open a web page and return its main text (up to max_chars). Use after web_search to read sources.",
      {"url": {"type": "string"}, "max_chars": {"type": "integer", "default": 6000}},
      ["url"])
def read_webpage(ctx, url, max_chars=6000):
    max_chars = max(500, min(int(max_chars), 8000))
    try:
        r, data, final = fetch(url)
    except ValueError as e:
        return ToolResult(False, str(e))
    if r.status_code >= 400:
        return ToolResult(False, f"HTTP {r.status_code} for {url}")
    ctype = r.headers.get("content-type", "")
    if "pdf" in ctype or final.lower().endswith(".pdf"):
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        title, text = final, "\n".join((pg.extract_text() or "") for pg in reader.pages[:30])
    elif "html" in ctype or data[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
        title, text = html_to_text(data.decode(_encoding(r, data), errors="replace"))
    elif ctype.startswith("text/") or "json" in ctype:
        title, text = final, data.decode(_encoding(r, data), errors="replace")
    else:
        return ToolResult(False, f"Unsupported content type: {ctype}")
    more = f"\n\n[... {len(text) - max_chars} more characters]" if len(text) > max_chars else ""
    return ToolResult(True, f"Title: {title}\nURL: {final}\n\n{text[:max_chars]}{more}")
