from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


@dataclass
class PageImage:
    page_number: int
    png_bytes: bytes
    width: int
    height: int

    @property
    def data_url(self) -> str:
        b64 = base64.b64encode(self.png_bytes).decode("ascii")
        return f"data:image/png;base64,{b64}"


@dataclass
class PdfPayload:
    filename: str
    page_count: int
    text: str
    pages: list[PageImage]


def render_pdf(path: Path, max_pages: int = 6, dpi: int = 160) -> PdfPayload:
    doc = fitz.open(path)
    page_count = doc.page_count
    texts: list[str] = []
    pages: list[PageImage] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    for i, page in enumerate(doc):
        texts.append(page.get_text("text") or "")
        if i >= max_pages:
            continue
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        pages.append(
            PageImage(
                page_number=i + 1,
                png_bytes=buf.getvalue(),
                width=pix.width,
                height=pix.height,
            )
        )

    doc.close()
    return PdfPayload(
        filename=path.name,
        page_count=page_count,
        text="\n".join(texts).strip(),
        pages=pages,
    )
