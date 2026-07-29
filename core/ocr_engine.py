import io
import statistics
from dataclasses import dataclass, field
from typing import Optional
import fitz  
import pdfplumber
import pytesseract
from PIL import Image
MIN_DIGITAL_CHARS = 25
TESSERACT_TRUST_THRESHOLD = 65
RENDER_DPI = 300


@dataclass
class PageResult:
    page_number: int
    raw_text: str
    method_used: str
    confidence: float
    image: Optional[Image.Image] = field(default=None, repr=False)
    notes: list = field(default_factory=list)


def _pdf_page_to_image(page: "fitz.Page") -> Image.Image:
    zoom = RENDER_DPI / 72
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def _run_tesseract_with_confidence(image: Image.Image) -> tuple[str, float]:
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    n = len(data["text"])
    lines: dict[tuple, list[str]] = {}
    confidences = []

    for i in range(n):
        word = data["text"][i].strip()
        conf_raw = data["conf"][i]
        conf = int(conf_raw) if str(conf_raw).lstrip("-").isdigit() else -1
        if not word or conf < 0:
            continue
        confidences.append(conf)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)

    text = "\n".join(" ".join(words) for words in lines.values())
    mean_conf = statistics.mean(confidences) if confidences else 0.0
    return text, mean_conf


def read_pdf(pdf_path: str) -> list[PageResult]:
    results: list[PageResult] = []

    with pdfplumber.open(pdf_path) as plumber_pdf:
        fitz_doc = fitz.open(pdf_path)

        for i, plumber_page in enumerate(plumber_pdf.pages):
            digital_text = (plumber_page.extract_text() or "").strip()
            if len(digital_text) >= MIN_DIGITAL_CHARS:
                results.append(PageResult(
                    page_number=i + 1,
                    raw_text=digital_text,
                    method_used="digital_text",
                    confidence=99.0,
                    notes=["Native PDF text layer used directly."],
                ))
                continue
            fitz_page = fitz_doc[i]
            page_image = _pdf_page_to_image(fitz_page)
            ocr_text, ocr_conf = _run_tesseract_with_confidence(page_image)
            if ocr_conf >= TESSERACT_TRUST_THRESHOLD and len(ocr_text) >= MIN_DIGITAL_CHARS:
                results.append(PageResult(
                    page_number=i + 1,
                    raw_text=ocr_text,
                    method_used="ocr_printed",
                    confidence=ocr_conf,
                    image=page_image,
                    notes=[f"Tesseract OCR, mean word confidence {ocr_conf:.1f}."],
                ))
                continue
            docai_text = None
            try:
                from core.gcs_ocr import upload_to_gcs, ocr_with_documentai
                gcs_uri = upload_to_gcs(pdf_path, "invoices")
                docai_text = ocr_with_documentai(gcs_uri)
            except Exception:
                pass  

            if docai_text and len(docai_text.strip()) >= MIN_DIGITAL_CHARS:
                results.append(PageResult(
                    page_number=i + 1,
                    raw_text=docai_text,
                    method_used="document_ai",
                    confidence=90.0,
                    image=page_image,
                    notes=[f"Document AI OCR used (Tesseract confidence was {ocr_conf:.1f})."],
                ))
            else:
                results.append(PageResult(
                    page_number=i + 1,
                    raw_text=ocr_text,
                    method_used="needs_vision_ai",
                    confidence=ocr_conf,
                    image=page_image,
                    notes=[
                        f"Tesseract confidence too low ({ocr_conf:.1f}) or too little text "
                        f"recognized — likely handwritten, stamped, rotated, or a poor scan. "
                        f"Routed to Vision AI extraction and flagged for review."
                    ],
                ))

        fitz_doc.close()

    return results