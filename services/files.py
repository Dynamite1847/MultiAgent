"""File upload processing: image base64 encoding and document text extraction."""
import base64
import io
from pathlib import Path
from typing import Optional


def process_image(file_bytes: bytes, mime_type: str) -> dict:
    """Convert image bytes to base64 data URL."""
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64}"
    return {
        "type": "image",
        "data_url": data_url,
        "mime_type": mime_type
    }


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract plain text from PDF."""
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text_parts = []
        for page in reader.pages:
            text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)
    except Exception as e:
        return f"[PDF 解析失败: {e}]"


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract plain text from DOCX."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except Exception as e:
        return f"[DOCX 解析失败: {e}]"


def extract_text_from_excel(file_bytes: bytes) -> str:
    """Extract text from Excel (.xlsx/.xls) — each sheet as a tab-separated table."""
    try:
        import pylightxl as xl
        # pylightxl only reads data and ignores all styles, avoiding openpyxl Fill errors
        db = xl.readxl(fn=io.BytesIO(file_bytes))
        parts = []
        for sheet_name in db.ws_names:
            ws = db.ws(sheet_name)
            rows = []
            for row in ws.rows:
                # Filter out completely empty rows
                if not any(str(c).strip() for c in row):
                    continue
                cells = [str(c) if c is not (None, "") else "" for c in row]
                rows.append("\t".join(cells))
            if rows:
                parts.append(f"[Sheet: {sheet_name}]\n" + "\n".join(rows))
        return "\n\n".join(parts) if parts else "[空 Excel 文件]"
    except Exception as e:
        return f"[Excel 解析失败: {e}]"


def extract_text_from_txt(file_bytes: bytes) -> str:
    """Decode TXT file."""
    for encoding in ["utf-8", "gbk", "latin-1"]:
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def process_document(file_bytes: bytes, filename: str, mime_type: str) -> dict:
    """Extract text from a document and return structured result."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" or mime_type == "application/pdf":
        text = extract_text_from_pdf(file_bytes)
    elif ext in (".docx", ".doc") or "word" in mime_type:
        text = extract_text_from_docx(file_bytes)
    elif ext in (".xlsx", ".xls") or "spreadsheet" in mime_type or "excel" in mime_type:
        text = extract_text_from_excel(file_bytes)
    elif ext in (".md", ".txt", ".csv", ".json") or "text" in mime_type:
        text = extract_text_from_txt(file_bytes)
    else:
        text = extract_text_from_txt(file_bytes)

    return {
        "type": "document",
        "filename": filename,
        "text": text,
        "char_count": len(text)
    }
