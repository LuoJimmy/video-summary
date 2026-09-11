from httpx import Response
import respx

from app.services.document import (
    DocumentError,
    candidate_page_urls,
    chunk_paragraphs,
    ensure_job_source_file,
    extract_html_bytes,
    extract_path,
    extract_pdf,
    extract_plain,
    extract_url,
    looks_scanned,
    office_preview_html,
    resolve_preview_file,
    webpage_preview_html,
)


def test_plain_and_markdown_chunks(tmp_path):
    path = tmp_path / "note.md"
    path.write_text("第一段内容足够长。\n\n## 标题\n\n第二段也要留下。", encoding="utf-8")
    extracted = extract_plain(path)
    assert extracted.segments
    assert extracted.segments[0].locator.startswith("第")
    assert "第一段" in extracted.segments[0].text


def test_chunk_paragraphs_assigns_locators():
    segments = chunk_paragraphs(["甲" * 20, "乙" * 20])
    assert [item.locator for item in segments]
    assert segments[0].start == 0


def test_extract_text_pdf(tmp_path):
    import fitz

    path = tmp_path / "text.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "这是数字PDF里的一段正文，用来入库知识库。" * 3, fontname="china-s")
    doc.save(path)
    doc.close()
    extracted = extract_pdf(path, ocr=lambda _: (_ for _ in ()).throw(AssertionError("不应走 OCR")))
    assert extracted.used_ocr is False
    assert "数字PDF" in extracted.segments[0].text
    assert extracted.segments[0].locator == "第1页"


def test_empty_pdf_uses_ocr(tmp_path):
    import fitz

    path = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    assert looks_scanned([""])

    def fake_ocr(_image):
        return [(["box", "扫描识别出来的正文", 0.9])], 0.1

    extracted = extract_pdf(path, ocr=fake_ocr)
    assert extracted.used_ocr is True
    assert "扫描识别" in extracted.segments[0].text


def test_scanned_pdf_calls_ocr_plugin(tmp_path, monkeypatch):
    import fitz

    path = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    called = {"ocr": False}

    def fake_engine(progress=None):
        called["ocr"] = True

        def run(_image):
            return [[["box"], "扫描识别出来的正文", 0.9]], 0.1

        return run

    monkeypatch.setattr("app.services.plugins.ensure_ocr_engine", fake_engine)
    extracted = extract_pdf(path)
    assert called["ocr"] is True
    assert extracted.used_ocr is True
    assert "扫描识别" in extracted.segments[0].text


def test_empty_text_file_fails(tmp_path):
    path = tmp_path / "blank.txt"
    path.write_text("   \n", encoding="utf-8")
    try:
        extract_path(path)
        raise AssertionError("should fail")
    except DocumentError as exc:
        assert "空" in str(exc)


def test_ensure_job_source_file_copies_into_workdir(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    monkeypatch.setattr(app_settings, "download_dir", "")
    original = tmp_path / "outside" / "note.txt"
    original.parent.mkdir()
    original.write_text("文档预览原文", encoding="utf-8")
    dest = ensure_job_source_file("job-preview", original)
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "文档预览原文"
    assert dest.parent == app_settings.job_workdir("job-preview")
    assert resolve_preview_file("job-preview", str(dest)) == dest.resolve()


def test_office_preview_html_contains_paragraphs(tmp_path):
    from docx import Document

    path = tmp_path / "source.docx"
    doc = Document()
    doc.add_paragraph("预览段落内容足够长。")
    doc.save(path)
    html = office_preview_html(path).decode("utf-8")
    assert "预览段落" in html
    assert 'id="seg-0"' in html


def test_webpage_preview_uses_extracted_text_not_spa_shell(tmp_path):
    path = tmp_path / "source.html"
    path.write_text(
        "<!doctype html><html><head><title>韭研公社</title></head>"
        "<body><div id='app'></div></body></html>",
        encoding="utf-8",
    )
    transcript = (
        '[{"id":0,"start":0,"end":0,"text":"每天十分钟阅读，开阔看盘思路。","locator":"第1段"}]'
    )
    html = webpage_preview_html(path, title="9月11日盘前纪要", transcript_json=transcript).decode(
        "utf-8"
    )
    assert "每天十分钟阅读" in html
    assert 'id="seg-0"' in html
    assert "9月11日盘前纪要" in html
    assert "id='app'" not in html


def test_webpage_preview_turns_newlines_into_breaks(tmp_path):
    path = tmp_path / "source.html"
    path.write_text("<html><body><div id='app'></div></body></html>", encoding="utf-8")
    transcript = (
        '[{"id":0,"start":0,"end":0,"text":"昨日回顾：\\n昨日大盘低开震荡。","locator":"第1段"}]'
    )
    html = webpage_preview_html(path, title="微信文章", transcript_json=transcript).decode("utf-8")
    assert "昨日回顾：" in html
    assert "<br />" in html
    assert "昨日大盘低开震荡。" in html


def test_webpage_preview_prefers_original_wechat_html(tmp_path):
    path = tmp_path / "source.html"
    path.write_text(
        "<!doctype html><html><head><title>壳</title></head><body>"
        '<h1 id="activity-name">美股大跌！重点是...</h1>'
        '<div id="js_content" class="rich_media_content" style="visibility: hidden; opacity: 0;">'
        "<p><span>昨日回顾：</span></p>"
        '<img data-src="https://mmbiz.qpic.cn/demo.png" />'
        "</div>"
        "<script>document.body.innerHTML='被脚本改掉'</script>"
        "</body></html>",
        encoding="utf-8",
    )
    html = webpage_preview_html(
        path,
        title="提取标题",
        transcript_json='[{"id":0,"start":0,"end":0,"text":"提取后的纯文本","locator":"第1段"}]',
        source_url="https://mp.weixin.qq.com/s/demo",
    ).decode("utf-8")
    assert "昨日回顾：" in html
    assert 'id="js_content"' in html
    assert "提取后的纯文本" not in html
    assert "<script" not in html.lower()
    assert "vs-original-preview" in html
    assert '<img src="https://mmbiz.qpic.cn/demo.png"' in html
    assert 'base href="https://mp.weixin.qq.com/s/demo"' in html


def test_webpage_preview_uses_embedded_article_not_site_chrome(tmp_path):
    path = tmp_path / "source.html"
    path.write_text(
        "<!doctype html><html data-n-head-ssr><head><title>9月11日盘前纪要-韭研公社</title></head>"
        "<body>异动 关注 社群 交易计划 产业库 登录注册"
        "<h1>9月11日盘前纪要</h1>"
        "<p>作者利益披露：原创，不作为证券推荐或投资建议。</p>"
        '<script>window.__NUXT__={data:[{data:{article_id:"abc",'
        'title:"9月11日盘前纪要",'
        'content:"\\u003Cp class=\\"MsoNormal\\"\\u003E每天十分钟阅读，开阔看盘思路。\\u003C/p\\u003E"'
        "}}]}</script></body></html>",
        encoding="utf-8",
    )
    html = webpage_preview_html(
        path,
        title="9月11日盘前纪要",
        transcript_json='[{"id":0,"start":0,"end":0,"text":"提取纯文本","locator":"第1段"}]',
    ).decode("utf-8")
    assert "每天十分钟阅读" in html
    assert "MsoNormal" in html
    assert "登录注册" not in html
    assert "提取纯文本" not in html
    assert 'id="seg-0"' not in html


def test_candidate_page_urls_rewrites_h5_article():
    url = "https://www.jiuyangongshe.com/h5/article/3y6r5wxqqgn"
    found = candidate_page_urls(url)
    assert found[0] == url
    assert "https://www.jiuyangongshe.com/a/3y6r5wxqqgn" in found


def test_empty_spa_html_fails():
    html = (
        "<!doctype html><html><head><title>韭研公社</title></head>"
        "<body><div id='__nuxt'><div id='app'></div></div>"
        "<script>window.__NUXT__={data:[{}]}</script></body></html>"
    ).encode("utf-8")
    try:
        extract_html_bytes(html)
        raise AssertionError("should fail")
    except DocumentError as exc:
        assert "正文" in str(exc)


def test_extract_html_from_nuxt_article():
    html = (
        "<!doctype html><html><head><title>壳标题</title></head><body>"
        '<script>window.__NUXT__=(function(){return {data:[{data:{article_id:"abc",'
        'title:"9月11日盘前纪要",content:"\\u003Cp\\u003E每天十分钟阅读，开阔看盘思路。\\u003C/p\\u003E"'
        "}}]}})();</script></body></html>"
    ).encode("utf-8")
    extracted = extract_html_bytes(html)
    assert extracted.title == "9月11日盘前纪要"
    assert "每天十分钟阅读" in extracted.segments[0].text
    assert "开阔看盘思路" in extracted.segments[0].text


def test_extract_html_from_jsonld_article():
    html = (
        "<!doctype html><html><head><title>页标题</title>"
        '<script type="application/ld+json">'
        '{"@type":"NewsArticle","headline":"利率会议前瞻",'
        '"author":{"name":"研报社"},"articleBody":"美联储即将公布议息结果。"}'
        "</script></head><body></body></html>"
    ).encode("utf-8")
    extracted = extract_html_bytes(html)
    assert extracted.title == "利率会议前瞻"
    assert extracted.author == "研报社"
    assert "美联储即将公布议息结果" in extracted.segments[0].text


def test_split_blocks_keeps_single_newlines():
    from app.services.document import _split_blocks, chunk_paragraphs

    blocks = _split_blocks("昨日回顾：\n昨日大盘低开震荡。\n今日题材：")
    assert blocks == ["昨日回顾：", "昨日大盘低开震荡。", "今日题材："]
    segments = chunk_paragraphs(blocks)
    assert "\n" in segments[0].text
    assert "昨日回顾：" in segments[0].text
    assert "今日题材：" in segments[0].text


def test_html_spans_in_paragraphs_stay_on_one_line():
    from app.services.document import _html_to_text, _split_blocks

    html = (
        "<div id='js_content'>"
        "<p><span>2026年09月11日</span><span>-周五-</span><span>大家早上好！</span></p>"
        "<p><span>看前点赞！好运不断！</span></p>"
        "<p><span>昨日回顾：</span></p>"
        "</div>"
    )
    text = _html_to_text(html)
    assert "2026年09月11日-周五-大家早上好！" in text.replace(" ", "").replace("\n", "")
    blocks = _split_blocks(text)
    assert blocks[0] == "2026年09月11日-周五-大家早上好！"
    assert "看前点赞！好运不断！" in blocks
    assert "昨日回顾：" in blocks

    extracted = extract_html_bytes(html.encode("utf-8"))
    joined = "\n".join(item.text for item in extracted.segments)
    assert "\n" in joined
    assert "看前点赞" in joined
    assert joined.count("看前点赞") == 1


@respx.mock
def test_extract_url_retries_h5_article_on_desktop_page(tmp_path):
    h5 = "https://www.jiuyangongshe.com/h5/article/abc123"
    desktop = "https://www.jiuyangongshe.com/a/abc123"
    shell = (
        "<!doctype html><html><head><title>韭研公社</title></head>"
        "<body><div id='app'></div></body></html>"
    )
    article = (
        "<!doctype html><html><head><title>壳</title></head><body>"
        '<script>window.__NUXT__={data:[{data:{article_id:"abc123",'
        'title:"盘前纪要",content:"\\u003Cp\\u003E每天十分钟看盘复盘。\\u003C/p\\u003E"}}]}</script>'
        "</body></html>"
    )
    respx.get(h5).mock(return_value=Response(200, text=shell, headers={"content-type": "text/html"}))
    respx.get(desktop).mock(return_value=Response(200, text=article, headers={"content-type": "text/html"}))
    extracted = extract_url(h5, tmp_path)
    assert extracted.title == "盘前纪要"
    assert "每天十分钟看盘复盘" in extracted.segments[0].text
