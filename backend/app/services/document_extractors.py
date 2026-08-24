from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from app.models.documents import CHUNK_CONTENT_MAX_LENGTH, DocumentChunk

MAX_CHARS = CHUNK_CONTENT_MAX_LENGTH
OVERLAP = 100


def chunk_extracted_content(
    document_id: UUID,
    document_name: str,
    items: list[dict],
    max_chars: int = MAX_CHARS,
    overlap: int = OVERLAP,
) -> list[DocumentChunk]:
    """按字符上限和重叠规则将已提取内容转换为可追溯的文档块。"""

    if max_chars > MAX_CHARS:
        raise ValueError(f"max_chars 不得超过 {MAX_CHARS}")
    if max_chars <= 0 or not 0 <= overlap < max_chars:
        raise ValueError("分块参数无效")
    chunks: list[DocumentChunk] = []
    for item in items:
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        chunk_type = item.get("chunk_type")
        if chunk_type not in {"text", "table", "chart_ocr"}:
            raise ValueError("未知块类型")
        start = 0
        while start < len(content):
            end = min(start + max_chars, len(content))
            part = content[start:end]
            chunks.append(
                DocumentChunk(
                    id=str(uuid4()),
                    document_id=str(document_id),
                    content=part,
                    chunk_type=chunk_type,
                    document_name=document_name,
                    source_page=item.get("source_page"),
                    source_section=item.get("source_section"),
                    source_table=item.get("source_table"),
                    source_figure=item.get("source_figure"),
                    image_path=item.get("image_path"),
                    char_start=start,
                    char_end=end,
                )
            )
            if end == len(content):
                break
            start = end - overlap
    return chunks


def extract_docx(path: Path | str, extracted_dir: Path | str) -> list[dict]:
    """提取 DOCX 正文、表格和嵌入图片，返回供分块使用的来源记录。"""

    from docx import Document

    document = Document(path)
    output_dir = Path(extracted_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    current_section: str | None = None
    table_index = 0
    figure_index = 0
    paragraphs_by_element = {paragraph._p: paragraph for paragraph in document.paragraphs}
    tables_by_element = {table._tbl: table for table in document.tables}
    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = paragraphs_by_element[element]
            text = paragraph.text.strip()
            if text:
                if paragraph.style.name.startswith(("Heading", "标题")):
                    current_section = text
                items.append({"content": text, "chunk_type": "text", "source_section": current_section})
            for blip in element.xpath(".//a:blip"):
                relation_id = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                relation = document.part.rels.get(relation_id)
                if relation is None:
                    continue
                figure_index += 1
                extension = Path(relation.target_ref).suffix or ".bin"
                image_name = f"figure-{figure_index}{extension.lower()}"
                image_bytes = relation.target_part.blob
                (output_dir / image_name).write_bytes(image_bytes)
                items.append({"content": "", "chunk_type": "chart_ocr", "source_section": current_section, "source_figure": figure_index, "image_path": image_name, "image_bytes": image_bytes})
        elif tag == "tbl":
            table = tables_by_element[element]
            table_index += 1
            rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
            content = "\n".join(row for row in rows if row.strip())
            if content:
                items.append({"content": content, "chunk_type": "table", "source_section": current_section, "source_table": table_index})
            for blip in element.xpath(".//a:blip"):
                relation_id = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                relation = document.part.rels.get(relation_id)
                if relation is None:
                    continue
                figure_index += 1
                extension = Path(relation.target_ref).suffix or ".bin"
                image_name = f"figure-{figure_index}{extension.lower()}"
                image_bytes = relation.target_part.blob
                (output_dir / image_name).write_bytes(image_bytes)
                items.append({"content": "", "chunk_type": "chart_ocr", "source_section": current_section, "source_table": table_index, "source_figure": figure_index, "image_path": image_name, "image_bytes": image_bytes})
    return items


def extract_pdf_with_pymupdf(path: Path | str, extracted_dir: Path | str) -> list[dict]:
    """使用 PyMuPDF 提取 PDF 文本和图片，作为 MinerU 的后备解析原语。"""

    import fitz

    output_dir = Path(extracted_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    document = fitz.open(path)
    try:
        figure_index = 0
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                items.append({"content": text, "chunk_type": "text", "source_page": page_number})
            for image in page.get_images(full=True):
                figure_index += 1
                image_data = document.extract_image(image[0])
                extension = image_data.get("ext", "bin")
                image_name = f"page-{page_number}-figure-{figure_index}.{extension}"
                (output_dir / image_name).write_bytes(image_data["image"])
                items.append(
                    {
                        "content": "PDF 图片",
                        "chunk_type": "chart_ocr",
                        "source_page": page_number,
                        "source_figure": figure_index,
                        "image_path": image_name,
                        "image_bytes": image_data["image"],
                    }
                )
    finally:
        document.close()
    return items
