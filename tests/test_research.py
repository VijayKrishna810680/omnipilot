"""Web research and chat-with-your-files tools (no real internet needed)."""
import json

import pytest

from core.agent import Context
from core.search import bm25, chunk
from core.tools import web
from core.tools.registry import run_tool

DDG_HTML = """
<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fai&amp;rut=x">AI <b>agents</b> news</a>
<a class="result__snippet" href="#">Agents are <b>everywhere</b> in 2026.</a></div>
<div class="result"><a rel="nofollow" class="result__a" href="https://docs.python.org/3/">Python docs</a>
<a class="result__snippet" href="#">Official documentation.</a></div>
"""
DDG_LITE = """<table><tr><td><a rel="nofollow" href="https://example.org/one" class='result-link'>First result</a></td></tr>
<tr><td class='result-snippet'>Snippet one</td></tr></table>"""


def test_parse_duckduckgo_html_and_lite():
    res = web.parse_ddg_html(DDG_HTML, 5)
    assert res[0] == {"title": "AI agents news", "url": "https://example.com/ai", "snippet": "Agents are everywhere in 2026."}
    assert res[1]["url"] == "https://docs.python.org/3/"
    lite = web.parse_ddg_lite(DDG_LITE, 5)
    assert lite == [{"title": "First result", "url": "https://example.org/one", "snippet": "Snippet one"}]


def test_web_search_falls_back_to_next_backend(env, monkeypatch):
    ws, mem, _ = env

    def broken(q, n):
        raise RuntimeError("blocked")

    monkeypatch.setattr(web, "SEARCH_BACKENDS", [("first", broken), ("second", lambda q, n: [
        {"title": "T", "url": "https://t.example", "snippet": "S"}])])
    res = run_tool("web_search", json.dumps({"query": "x"}), Context(ws, mem))
    assert res.ok and "second" in res.output and "https://t.example" in res.output


@pytest.mark.parametrize("url", ["http://127.0.0.1:8501/", "http://localhost/admin", "http://169.254.169.254/latest/meta-data",
                                 "http://10.0.0.5/", "file:///etc/passwd", "ftp://example.com/x"])
def test_private_and_non_http_urls_are_blocked(url):
    with pytest.raises(ValueError):
        web.check_url(url)


def test_html_to_text_keeps_content_drops_scripts():
    title, text = web.html_to_text("<html><head><title>My Page</title><script>evil()</script></head><body>"
                                   "<nav>Menu</nav><h1>Hello</h1><p>World &amp; more</p></body></html>")
    assert title == "My Page"
    assert "Hello" in text and "World & more" in text
    assert "evil" not in text and "Menu" not in text


def test_chunk_and_bm25():
    parts = chunk("Sentence one about cats. " * 100, size=300, overlap=50)
    assert len(parts) > 3 and all(len(p) <= 300 for p in parts)
    ranked = bm25("refund policy", ["shipping takes 3 days", "our refund policy allows returns in 30 days", "hello"])
    assert ranked[0][1] == 1


def test_search_files_finds_right_file_and_page(env):
    from docx import Document
    from reportlab.pdfgen import canvas
    ws, mem, _ = env
    pdf = canvas.Canvas(str(ws.path("handbook.pdf")))
    pdf.drawString(72, 720, "Welcome to the company handbook.")
    pdf.showPage()
    pdf.drawString(72, 720, "Leave policy: employees get 24 paid leave days per year.")
    pdf.save()
    doc = Document()
    doc.add_paragraph("The office cafeteria opens at 9 am.")
    doc.save(ws.path("office.docx"))
    ws.path("notes.txt").write_text("Project Phoenix launches in March.")
    res = run_tool("search_files", json.dumps({"query": "how many paid leave days"}), Context(ws, mem))
    assert res.ok
    first = res.output.split("---")[0]
    assert "handbook.pdf, page 2" in first and "24 paid leave days" in first
    res2 = run_tool("search_files", json.dumps({"query": "cafeteria opens"}), Context(ws, mem))
    assert "office.docx" in res2.output.split("---")[0]


def test_search_files_without_files_says_upload(env):
    ws, mem, _ = env
    res = run_tool("search_files", json.dumps({"query": "anything"}), Context(ws, mem))
    assert not res.ok and "upload" in res.output.lower()
