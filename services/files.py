"""File upload processing: image base64 encoding and document text extraction.

Uses Microsoft MarkItDown for document-to-Markdown conversion.
Supports: PDF, Word, Excel, PowerPoint, HTML, CSV, JSON, XML, EPub, ZIP, audio, and more.
"""
import base64
import io
import tempfile
import os
from pathlib import Path
from typing import Optional

from markitdown import MarkItDown

# Singleton MarkItDown instance (no LLM needed for basic conversion)
_md = MarkItDown(enable_plugins=False)


def process_image(file_bytes: bytes, mime_type: str) -> dict:
    """Convert image bytes to base64 data URL."""
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64}"
    return {
        "type": "image",
        "data_url": data_url,
        "mime_type": mime_type
    }


def process_document(file_bytes: bytes, filename: str, mime_type: str) -> dict:
    """Extract text from a document using MarkItDown and return structured result.

    MarkItDown converts documents to Markdown, preserving structure like
    headings, tables, lists, and links — ideal for LLM consumption.
    """
    text = _convert_with_markitdown(file_bytes, filename)

    return {
        "type": "document",
        "filename": filename,
        "text": text,
        "char_count": len(text)
    }


def _convert_with_markitdown(file_bytes: bytes, filename: str) -> str:
    """Convert file bytes to Markdown text via MarkItDown.

    MarkItDown requires a file path or stream with extension info,
    so we write to a temp file preserving the original extension.
    """
    ext = Path(filename).suffix
    tmp_fd = None
    tmp_path = None
    try:
        # Create temp file with original extension for correct format detection
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(file_bytes)
            tmp_fd = None  # fd is now closed by os.fdopen

        result = _md.convert(tmp_path)
        text = result.text_content or ""

        if not text.strip():
            return f"[{filename}: 文档无可提取的文本内容]"
        return text

    except Exception as e:
        return f"[{filename} 解析失败: {e}]"
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
