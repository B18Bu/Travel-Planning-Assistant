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


def test_chunking_preserves_source_and_splits_long_text_with_100_char_overlap():
    document_id = uuid4()
    text = "甲" * 900

    chunks = chunk_extracted_content(
        document_id=document_id,
        document_name="报告.pdf",
        items=[{"content": text, "chunk_type": "text", "source_page": 2}],
    )

    assert [len(chunk.content) for chunk in chunks] == [800, 200]
    assert chunks[0].content[-100:] == chunks[1].content[:100]
    assert all(chunk.source_page == 2 for chunk in chunks)
    assert all(chunk.document_id == str(document_id) for chunk in chunks)
    assert chunks[0].char_start == 0 and chunks[0].char_end == 800
    assert chunks[1].char_start == 700 and chunks[1].char_end == 900


def test_chunking_applies_same_limit_to_tables_and_preserves_table_location():
    document_id = uuid4()
    chunks = chunk_extracted_content(
        document_id=document_id,
        document_name="报告.docx",
        items=[{"content": "表格" * 500, "chunk_type": "table", "source_table": 3}],
    )

    assert len(chunks) == 2
    assert all(chunk.chunk_type == "table" for chunk in chunks)
    assert all(chunk.source_table == 3 for chunk in chunks)
    assert all(len(chunk.content) <= 800 for chunk in chunks)


def test_chunking_rejects_a_limit_larger_than_document_chunk_contract():
    with pytest.raises(ValueError, match="不得超过 800"):
        chunk_extracted_content(
            document_id=uuid4(),
            document_name="报告.docx",
            items=[{"content": "正文", "chunk_type": "text"}],
            max_chars=801,
        )


@pytest.mark.skipif(Document is None, reason="未安装 python-docx")
def test_extract_docx_preserves_mixed_body_order_tracks_section_and_links_images(tmp_path):
    image_path = tmp_path / "chart.png"
    image_path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLCCgAAAABJRU5ErkJggg=="
    ))
    path = tmp_path / "report.docx"
    document = Document()
    document.add_heading("调研摘要", level=1)
    document.add_paragraph("正文内容")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "景点"
    table.cell(0, 1).text = "古城"
    document.add_picture(str(image_path))
    document.save(path)

    extracted = extract_docx(path, tmp_path / "extracted")

    assert [item["chunk_type"] for item in extracted] == ["text", "text", "table", "chart_ocr"]
    assert [item["content"] for item in extracted[:3]] == ["调研摘要", "正文内容", "景点 | 古城"]
    assert extracted[1]["source_section"] == "调研摘要"
    assert extracted[2]["source_section"] == "调研摘要"
    assert extracted[2]["source_table"] == 1
    image = extracted[3]
    assert image["content"] == ""
    assert image["source_section"] == "调研摘要"
    assert image["source_figure"] == 1
    assert image["image_path"] == "figure-1.png"
    assert (tmp_path / "extracted" / image["image_path"]).read_bytes() == image["image_bytes"]


@pytest.mark.skipif(Document is None, reason="未安装 python-docx")
def test_extract_docx_exports_image_inside_table_with_table_source(tmp_path):
    image_path = tmp_path / "chart.png"
    image_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLCCgAAAABJRU5ErkJggg=="))
    path = tmp_path / "report.docx"
    document = Document()
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).paragraphs[0].add_run().add_picture(str(image_path))
    document.save(path)

    extracted = extract_docx(path, tmp_path / "extracted")

    image = next(item for item in extracted if item["chunk_type"] == "chart_ocr")
    assert image["source_table"] == 1
    assert image["source_figure"] == 1
    assert (tmp_path / "extracted" / image["image_path"]).read_bytes() == image["image_bytes"]


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
