from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from localmind.models.manager import ModelManager

from .types import Document, PageContent

logger = logging.getLogger(__name__)


def ingest_text(path: Path, **_kwargs) -> Document:
    text = path.read_text(encoding="utf-8", errors="replace")
    return Document(
        source=str(path),
        text=text,
        pages=[PageContent(page_number=1, text=text)],
        metadata={"type": "text", "extension": path.suffix},
    )


def ingest_pdf(path: Path, model_manager: ModelManager, **_kwargs) -> Document:
    import fitz

    doc = fitz.open(str(path))
    pages: list[PageContent] = []
    all_text_parts: list[str] = []
    ocr_model = None
    ocr_tokenizer = None

    for i, page in enumerate(doc):
        text = page.get_text()

        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        if len(text.strip()) < 50:
            if ocr_model is None:
                ocr_model, ocr_tokenizer = model_manager.get_ocr_model()
            text = _run_ocr(ocr_model, ocr_tokenizer, img)

        pages.append(PageContent(page_number=i + 1, text=text, image=img))
        all_text_parts.append(text)

    doc.close()
    return Document(
        source=str(path),
        text="\n\n".join(all_text_parts),
        pages=pages,
        metadata={"type": "pdf", "num_pages": len(pages)},
    )


def ingest_image(path: Path, model_manager: ModelManager, **_kwargs) -> Document:
    img = Image.open(path).convert("RGB")
    ocr_model, ocr_tokenizer = model_manager.get_ocr_model()
    text = _run_ocr(ocr_model, ocr_tokenizer, img)

    return Document(
        source=str(path),
        text=text,
        pages=[PageContent(page_number=1, text=text, image=img)],
        metadata={"type": "image", "size": img.size},
    )


def ingest_audio(path: Path, model_manager: ModelManager, **_kwargs) -> Document:
    whisper = model_manager.get_whisper()
    segments, info = whisper.transcribe(str(path), beam_size=5)

    text_parts = [segment.text for segment in segments]
    text = " ".join(text_parts)

    return Document(
        source=str(path),
        text=text,
        pages=[PageContent(page_number=1, text=text)],
        metadata={
            "type": "audio",
            "language": info.language,
            "duration_seconds": info.duration,
        },
    )


def ingest_latex(path: Path, **_kwargs) -> Document:
    from pylatexenc.latex2text import LatexNodes2Text

    raw = path.read_text(encoding="utf-8", errors="replace")
    converter = LatexNodes2Text()
    text = converter.latex_to_text(raw)

    return Document(
        source=str(path),
        text=text,
        pages=[PageContent(page_number=1, text=text)],
        metadata={"type": "latex"},
    )


def _run_ocr(model, tokenizer, image: Image.Image) -> str:
    import torch

    prompt = "OCR the text in this image."
    inputs = tokenizer.apply_chat_template(
        [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}],
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    )
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    inputs["pixel_values"] = (
        tokenizer.image_processor(image, return_tensors="pt")["pixel_values"]
        .to(model.device, dtype=torch.bfloat16)
    )

    with torch.inference_mode():
        output_ids = model.generate(**inputs, max_new_tokens=4096)

    input_len = inputs["input_ids"].shape[1]
    return tokenizer.decode(output_ids[0][input_len:], skip_special_tokens=True)


HANDLER_MAP = {
    ".txt": ingest_text,
    ".md": ingest_text,
    ".pdf": ingest_pdf,
    ".png": ingest_image,
    ".jpg": ingest_image,
    ".jpeg": ingest_image,
    ".webp": ingest_image,
    ".mp3": ingest_audio,
    ".wav": ingest_audio,
    ".flac": ingest_audio,
    ".m4a": ingest_audio,
    ".ogg": ingest_audio,
    ".tex": ingest_latex,
}
