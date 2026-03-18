"""OCR engine using RapidOCR + PyMuPDF for text extraction."""

import io
import logging
from pathlib import Path

import fitz  # pymupdf
import numpy as np
from PIL import Image

from .utils import is_credit_card_statement

logger = logging.getLogger(__name__)

_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _load_image(file_path: Path) -> Image.Image:
    """Load image file, supporting HEIC format."""
    suffix = file_path.suffix.lower()
    if suffix in (".heic", ".heif"):
        from pillow_heif import register_heif_opener
        register_heif_opener()
    return Image.open(file_path).convert("RGB")


def _pdf_extract_text(file_path: Path) -> str:
    """Try to extract embedded text from PDF."""
    doc = fitz.open(file_path)
    all_text = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            all_text.append(text.strip())
    doc.close()
    return "\n\n".join(all_text)


def _pdf_to_images(file_path: Path, dpi: int = 300) -> list[np.ndarray]:
    """Render PDF pages to images."""
    doc = fitz.open(file_path)
    images = []
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        if pix.n == 4:  # RGBA → RGB
            img = img[:, :, :3]
        images.append(img)
    doc.close()
    return images


def ocr_image(img: np.ndarray) -> list[dict]:
    """Run OCR on a numpy image array.
    Returns list of {text, bbox, confidence}.
    """
    engine = _get_ocr()
    result, _ = engine(img)
    if not result:
        return []
    entries = []
    for line in result:
        bbox, text, confidence = line
        entries.append({
            "text": text,
            "bbox": bbox,  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            "confidence": float(confidence),
        })
    return entries


def extract_text_from_file(file_path: Path, dpi: int = 300) -> dict:
    """Extract all text from a file.

    Returns:
        {
            "text": str,           # Full combined text
            "pages": [{            # Per-page data
                "text": str,
                "ocr_entries": [...],  # With bbox info
                "image": np.ndarray | None
            }],
            "method": "embedded" | "ocr",
            "source_file": str
        }
    """
    suffix = file_path.suffix.lower()
    result = {"source_file": file_path.name, "pages": [], "text": "", "method": ""}

    if suffix == ".pdf":
        # Try embedded text first
        embedded = _pdf_extract_text(file_path)
        is_cc = is_credit_card_statement(file_path.name)

        if len(embedded) > 50:  # Meaningful text found
            result["text"] = embedded
            result["method"] = "embedded"

            if is_cc:
                # Credit card statements need page images for highlight detection
                images = _pdf_to_images(file_path, dpi=dpi)
                for i, img in enumerate(images):
                    result["pages"].append({
                        "text": embedded if i == 0 else "",
                        "ocr_entries": [],
                        "image": img,
                    })
                logger.info(f"PDF embedded text + images for credit card: {file_path.name}")
            else:
                result["pages"] = [{"text": embedded, "ocr_entries": [], "image": None}]
                logger.info(f"PDF embedded text extracted: {file_path.name}")
            return result

        # Fall back to OCR
        images = _pdf_to_images(file_path, dpi=dpi)
        all_text = []
        for i, img in enumerate(images):
            entries = ocr_image(img)
            page_text = "\n".join(e["text"] for e in entries)
            all_text.append(page_text)
            result["pages"].append({
                "text": page_text,
                "ocr_entries": entries,
                "image": img,
            })
        result["text"] = "\n\n".join(all_text)
        result["method"] = "ocr"
        logger.info(f"PDF OCR completed ({len(images)} pages): {file_path.name}")

    else:
        # Image file
        img = _load_image(file_path)
        img_array = np.array(img)
        entries = ocr_image(img_array)
        page_text = "\n".join(e["text"] for e in entries)
        result["text"] = page_text
        result["method"] = "ocr"
        result["pages"] = [{"text": page_text, "ocr_entries": entries, "image": img_array}]
        logger.info(f"Image OCR completed: {file_path.name}")

    return result


def get_file_preview_image(file_path: Path, max_width: int = 800) -> Image.Image | None:
    """Get a preview image for display in Streamlit."""
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".pdf":
            doc = fitz.open(file_path)
            page = doc[0]
            zoom = min(max_width / page.rect.width, 2.0)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            doc.close()
            return img
        else:
            img = _load_image(file_path)
            if img.width > max_width:
                ratio = max_width / img.width
                img = img.resize((max_width, int(img.height * ratio)))
            return img
    except Exception as e:
        logger.warning(f"无法生成预览: {file_path.name}: {e}")
        return None
