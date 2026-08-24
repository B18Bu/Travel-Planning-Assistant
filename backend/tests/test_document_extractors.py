import base64
from uuid import uuid4

import pytest

try:
    from docx import Document
except ImportError:
    Document = None
try:
    import fitz
except ImportError:
    fitz = None

from app.services.document_extractors import (
    chunk_extracted_content,
    extract_docx,
    extract_pdf_with_pymupdf,
)


@pytest.mark.skipif(Document is None, reason="未安装 python-docx")
def test_extract_docx_keeps_heading_paths_body_order_and_semantic_table(tmp_path):
    path = tmp_path / "report.docx"
    document = Document()
    document.add_paragraph("前言")
    document.add_heading("行程方案", level=1)
    document.add_paragraph("概览")
    document.add_heading("第一天", level=2)
    document.add_paragraph("上午游览")
    table = document.add_table(rows=3, cols=3)
    for row, values in zip(table.rows, (("景点", "时段", ""), ("古城", "上午", ""), ("博物馆", "", "室内"))):
        for cell, value in zip(row.cells, values):
            cell.text = value
    document.add_heading("注意事项", level=1)
    document.add_paragraph("携带雨具")
    document.save(path)

    extracted = extract_docx(path, tmp_path / "extracted")

    assert [item["content"] for item in extracted] == [
        "前言", "行程方案", "概览", "第一天", "上午游览",
        "章节：行程方案 > 第一天\n表格 1\n表头：景点 | 时段 | 第 3 列\n第 2 行：景点=古城；时段=上午；第 3 列=\n第 3 行：景点=博物馆；时段=；第 3 列=室内",
        "注意事项", "携带雨具",
    ]
    assert [item["section_path"] for item in extracted] == [
        (), ("行程方案",), ("行程方案",), ("行程方案", "第一天"),
        ("行程方案", "第一天"), ("行程方案", "第一天"),
        ("注意事项",), ("注意事项",),
    ]
    assert [item["source_section"] for item in extracted] == [
        "正文", "行程方案", "行程方案", "行程方案 > 第一天",
        "行程方案 > 第一天", "行程方案 > 第一天", "注意事项", "注意事项",
    ]
    assert [item["source_order"] for item in extracted] == list(range(1, 9))
    assert extracted[5]["source_table"] == 1


def test_chunking_aggregates_adjacent_text_but_keeps_tables_as_boundaries():
    document_id = uuid4()
    items = [
        {"content": "甲段", "chunk_type": "text", "section_path": (), "source_section": "正文", "source_order": 1},
        {"content": "乙段", "chunk_type": "text", "section_path": (), "source_section": "正文", "source_order": 2},
        {"content": "章节：正文\n表格 1\n表头：项目\n第 2 行：项目=值", "chunk_type": "table", "source_section": "正文", "source_table": 1, "source_order": 3},
        {"content": "丙段", "chunk_type": "text", "section_path": (), "source_section": "正文", "source_order": 4},
    ]

    chunks = chunk_extracted_content(document_id, "报告.docx", items)

    assert [chunk.content for chunk in chunks] == [
        "甲段\n\n乙段", "章节：正文\n表格 1\n表头：项目\n第 2 行：项目=值", "丙段",
    ]
    assert [chunk.chunk_type for chunk in chunks] == ["text", "table", "text"]
    assert [(chunk.char_start, chunk.char_end) for chunk in chunks] == [(0, 6), (0, 10), (0, 2)]


def test_chunking_prefers_sentence_boundaries_and_tracks_body_offsets():
    document_id = uuid4()
    body = "甲" * 12 + "。" + "乙" * 12 + "。"

    chunks = chunk_extracted_content(
        document_id, "报告.docx",
        [{"content": body, "chunk_type": "text", "section_path": ("行程",), "source_section": "行程", "source_order": 1}],
        max_chars=30, overlap=5,
    )

    assert [chunk.content for chunk in chunks] == ["章节：行程\n\n甲甲甲甲甲甲甲甲甲甲甲甲。", "章节：行程\n\n甲甲甲甲。乙乙乙乙乙乙乙乙乙乙乙乙。"]
    assert [(chunk.char_start, chunk.char_end) for chunk in chunks] == [(0, 13), (8, 26)]
    assert all(len(chunk.content) <= 30 for chunk in chunks)


def test_chunking_splits_tables_by_rows_with_repeated_context_and_continues_long_rows():
    document_id = uuid4()
    content = (
        "章节：行程\n表格 2\n表头：景点 | 说明\n"
        "第 2 行：景点=古城；说明=推荐。\n"
        f"第 3 行：景点=博物馆；说明={'甲' * 50}"
    )

    chunks = chunk_extracted_content(
        document_id, "报告.docx",
        [{"content": content, "chunk_type": "table", "source_section": "行程", "source_table": 2, "source_order": 1}],
        max_chars=70, overlap=5,
    )

    assert len(chunks) >= 3
    assert all(chunk.content.startswith("章节：行程\n表格 2\n表头：景点 | 说明\n") for chunk in chunks)
    assert chunks[0].content.endswith("第 2 行：景点=古城；说明=推荐。")
    assert any("第 3 行（续）" in chunk.content for chunk in chunks[1:])
    assert all(chunk.chunk_type == "table" and len(chunk.content) <= 70 for chunk in chunks)


def test_chunking_chart_ocr_gets_its_own_context_and_text_overlap():
    document_id = uuid4()
    ocr_text = "图" * 30

    chunks = chunk_extracted_content(
        document_id, "报告.docx",
        [
            {"content": "前文", "chunk_type": "text", "section_path": ("行程",), "source_section": "行程", "source_order": 1},
            {"content": ocr_text, "chunk_type": "chart_ocr", "source_section": "行程", "source_figure": 4, "source_order": 2},
        ],
        max_chars=30, overlap=5,
    )

    assert chunks[0].content == "章节：行程\n\n前文"
    chart_chunks = chunks[1:]
    assert all(chunk.chunk_type == "chart_ocr" for chunk in chart_chunks)
    assert all(chunk.content.startswith("章节：行程\n图表 4\n\n") for chunk in chart_chunks)
    assert chart_chunks[0].content[-5:] == chart_chunks[1].content[len("章节：行程\n图表 4\n\n"):][:5]
    assert [(chunk.source_section, chunk.source_figure) for chunk in chart_chunks] == [("行程", 4)] * len(chart_chunks)


def test_chunking_rejects_a_limit_larger_than_document_chunk_contract():
    with pytest.raises(ValueError, match="不得超过 800"):
        chunk_extracted_content(
            document_id=uuid4(), document_name="报告.docx",
            items=[{"content": "正文", "chunk_type": "text"}], max_chars=801,
        )


@pytest.mark.skipif(fitz is None, reason="未安装 PyMuPDF")
def test_extract_pdf_with_pymupdf_returns_page_text_and_exports_images(tmp_path):
    pdf_path = tmp_path / "report.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Travel research")
    page.insert_image(fitz.Rect(72, 100, 100, 128), stream=base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
    ))
    document.save(pdf_path)
    document.close()

    extracted = extract_pdf_with_pymupdf(pdf_path, tmp_path / "extracted")

    assert extracted[0] == {"content": "Travel research", "chunk_type": "text", "source_page": 1}
    image = extracted[1]
    assert image["chunk_type"] == "chart_ocr"
    assert image["source_page"] == 1
    assert image["source_figure"] == 1
    assert (tmp_path / "extracted" / image["image_path"]).exists()
